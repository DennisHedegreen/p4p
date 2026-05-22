from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

from fastapi import HTTPException, status
from pydantic import HttpUrl

from p4p_core import (
    HeartbeatRequest,
    NodeDelegation,
    NodeManifest,
    NodeManifestKey,
    NodeManifestRequest,
    NodeRootRotation,
    utc_now,
)
from p4p_core.constants import MAX_SIGNED_AT_FUTURE_SKEW_SECONDS, PROTOCOL_VERSION, DelegationCapability
from p4p_identity import verify_payload

from registry.config import RegistryConfig, normalized_registry_url
from registry.models import IdentityScope, Node, RegistrySourceResponse, RegistrySourceSnapshot, TrustClaimRecord
from registry.store import RegistryStore, StoredManifest, StoredNode


def has_node_signature_fields(node: Node) -> bool:
    return bool(node.node_public_key or node.signed_at or node.signature)


def node_payload(node: Node) -> dict[str, Any]:
    return node.model_dump(mode="json", exclude_none=True)


def announcement_hash(node: Node) -> str:
    raw = json.dumps(node_payload(node), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def registry_source_hash(payload: RegistrySourceSnapshot | RegistrySourceResponse) -> str:
    raw = json.dumps(
        payload.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def registry_source_content_hash(payload: RegistrySourceSnapshot | RegistrySourceResponse) -> str:
    raw = json.dumps(
        payload.model_dump(
            mode="json",
            exclude={"exported_at", "signature"},
            exclude_none=True,
        ),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def heartbeat_payload(payload: HeartbeatRequest) -> dict[str, Any]:
    return payload.model_dump(mode="json", exclude_none=True)


def manifest_payload(manifest: NodeManifest) -> dict[str, Any]:
    return {
        "node_id": manifest.node_id,
        "root_public_key": manifest.root_public_key,
        "manifest_version": manifest.manifest_version,
        "issued_at": manifest.issued_at,
        "keys": [entry.model_dump(mode="json", exclude_none=True) for entry in manifest.keys],
    }


def root_rotation_payload(rotation: NodeRootRotation) -> dict[str, Any]:
    return {
        "node_id": rotation.node_id,
        "previous_root_public_key": rotation.previous_root_public_key,
        "next_root_public_key": rotation.next_root_public_key,
        "rotated_at": rotation.rotated_at,
    }


def trust_claim_payload(record: TrustClaimRecord) -> dict[str, Any]:
    return record.model_dump(mode="json", exclude={"signature"}, exclude_none=True)


def identity_scope(endpoint: HttpUrl) -> IdentityScope:
    if endpoint.scheme == "http" and endpoint.host in {"127.0.0.1", "localhost"}:
        return "loopback"
    return "public"


def is_loopback_url(url: HttpUrl) -> bool:
    return url.scheme == "http" and url.host in {"127.0.0.1", "localhost"}


def is_loopback_registry_url(value: str | object) -> bool:
    normalized = str(value).strip()
    if not normalized:
        return False
    parts = urlsplit(normalized)
    return parts.scheme == "http" and parts.hostname in {"127.0.0.1", "localhost"}


def require_registry_capability(enabled: bool, *, detail: str) -> None:
    if enabled:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_registry_signing_key(config: RegistryConfig) -> tuple[str, str]:
    if not config.registry_private_key or not config.registry_public_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="This registry cannot issue signed trust claims without a registry signing key",
        )
    return config.registry_private_key, config.registry_public_key


def require_canonical_registry_url(config: RegistryConfig, *, detail: str) -> str:
    if config.registry_url:
        return config.registry_url
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=detail,
    )


def parse_timestamp(value: str, *, field_name: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be a valid RFC 3339 timestamp",
        ) from exc
    if parsed.tzinfo is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must include timezone information",
        )
    return parsed.astimezone(timezone.utc)


def require_not_too_far_in_future(value: datetime, *, field_name: str) -> None:
    now = utc_now()
    if value > now + timedelta(seconds=MAX_SIGNED_AT_FUTURE_SKEW_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} is too far in the future",
        )


def require_valid_trust_claim(record: TrustClaimRecord) -> None:
    require_not_too_far_in_future(record.issued_at, field_name="issued_at")
    if record.expires_at is not None and record.expires_at <= record.issued_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="expires_at must be later than issued_at for a trust claim",
        )
    if not verify_payload(
        trust_claim_payload(record),
        record.issuer_registry_public_key,
        record.signature,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid trust claim signature",
        )


def require_monotonic_signed_event(
    *,
    signed_at: datetime,
    stored: StoredNode | None,
    field_name: str,
) -> None:
    require_not_too_far_in_future(signed_at, field_name=field_name)
    if stored and stored.last_signed_event_at and signed_at <= stored.last_signed_event_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{field_name} must be newer than the last accepted signed event for this node_id",
        )


def require_valid_node_signature(node: Node) -> None:
    if not node.node_public_key or not node.signed_at or not node.signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Signed announcements require node_public_key, signed_at, and signature",
        )
    try:
        valid = verify_payload(node_payload(node), node.node_public_key, node.signature)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid node announcement signature",
        )


def manifest_key_expiry(value: str | None, *, field_name: str) -> datetime | None:
    if value is None:
        return None
    return parse_timestamp(value, field_name=field_name)


def require_manifest_key_state(
    key: NodeManifestKey,
    *,
    field_name: str,
    required_capability: DelegationCapability | None,
) -> None:
    if key.status != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="node_public_key has been revoked in current node manifest",
        )
    if required_capability and required_capability not in key.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Current node manifest does not allow {required_capability}",
        )
    expires_at = manifest_key_expiry(key.expires_at, field_name=field_name)
    if expires_at is not None and expires_at <= utc_now():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current node manifest entry has expired",
        )


def manifest_key_is_currently_active(key: NodeManifestKey) -> bool:
    if key.status != "active":
        return False
    expires_at = manifest_key_expiry(key.expires_at, field_name="manifest.keys[].expires_at")
    if expires_at is not None and expires_at <= utc_now():
        return False
    return True


def manifest_key_for_node(*, manifest: NodeManifest, node: Node) -> NodeManifestKey | None:
    if not node.node_public_key or not node.delegation:
        return None
    if node.delegation.root_public_key != manifest.root_public_key:
        return None
    for entry in manifest.keys:
        if entry.node_public_key != node.node_public_key:
            continue
        if entry.role != node.delegation.role:
            return None
        if not set(node.delegation.capabilities).issubset(set(entry.capabilities)):
            return None
        delegation_expires_at = manifest_key_expiry(
            node.delegation.expires_at,
            field_name="delegation.expires_at",
        )
        key_expires_at = manifest_key_expiry(
            entry.expires_at,
            field_name="manifest.keys[].expires_at",
        )
        if delegation_expires_at and key_expires_at and delegation_expires_at > key_expires_at:
            return None
        return entry
    return None


def delegation_payload(node: Node) -> dict[str, Any]:
    if not node.node_public_key or not node.delegation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delegated announcements require node_public_key and delegation",
        )
    return {
        "node_id": node.node_id,
        "node_public_key": node.node_public_key,
        "root_public_key": node.delegation.root_public_key,
        "issued_at": node.delegation.issued_at,
        "expires_at": node.delegation.expires_at,
        "role": node.delegation.role,
        "capabilities": node.delegation.capabilities,
    }


def require_active_delegation(
    delegation: NodeDelegation,
    *,
    field_name: str,
    required_capability: DelegationCapability,
) -> None:
    issued_at = parse_timestamp(delegation.issued_at, field_name=field_name)
    require_not_too_far_in_future(issued_at, field_name=field_name)
    if required_capability not in delegation.capabilities:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Delegation does not allow {required_capability}",
        )
    if delegation.expires_at is None:
        return
    expires_at = parse_timestamp(delegation.expires_at, field_name="delegation.expires_at")
    if expires_at <= issued_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="delegation.expires_at must be later than delegation.issued_at",
        )
    if expires_at <= utc_now():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delegation has expired",
        )


def require_valid_manifest_update(
    payload: NodeManifestRequest,
    *,
    existing: StoredManifest | None,
) -> None:
    manifest = payload.manifest
    issued_at = parse_timestamp(manifest.issued_at, field_name="manifest.issued_at")
    require_not_too_far_in_future(issued_at, field_name="manifest.issued_at")

    for entry in manifest.keys:
        expires_at = manifest_key_expiry(entry.expires_at, field_name="manifest.keys[].expires_at")
        if expires_at is not None and expires_at <= issued_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="manifest key expires_at must be later than manifest.issued_at",
            )

    try:
        valid = verify_payload(
            manifest_payload(manifest),
            manifest.root_public_key,
            manifest.signature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid node manifest signature",
        )

    if existing is None:
        if payload.root_rotation is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="root_rotation requires an existing node manifest",
            )
        return

    current_manifest = existing.manifest
    current_issued_at = parse_timestamp(current_manifest.issued_at, field_name="current_manifest.issued_at")

    if manifest.manifest_version <= current_manifest.manifest_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="manifest.manifest_version must be newer than the current node manifest",
        )
    if issued_at <= current_issued_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="manifest.issued_at must be newer than the current node manifest",
        )

    if manifest.root_public_key == current_manifest.root_public_key:
        if payload.root_rotation is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="root_rotation is only allowed when root_public_key changes",
            )
        return

    rotation = payload.root_rotation
    if rotation is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="root_public_key change requires previous-root rotation proof",
        )
    if rotation.node_id != manifest.node_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="root_rotation.node_id must match manifest.node_id",
        )
    if rotation.previous_root_public_key != current_manifest.root_public_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="root_rotation.previous_root_public_key does not match current root",
        )
    if rotation.next_root_public_key != manifest.root_public_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="root_rotation.next_root_public_key does not match manifest root",
        )

    rotated_at = parse_timestamp(rotation.rotated_at, field_name="root_rotation.rotated_at")
    require_not_too_far_in_future(rotated_at, field_name="root_rotation.rotated_at")
    if rotated_at <= current_issued_at:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="root_rotation.rotated_at must be newer than the current node manifest",
        )
    if issued_at < rotated_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="manifest.issued_at must be at or after root_rotation.rotated_at",
        )

    try:
        valid = verify_payload(
            root_rotation_payload(rotation),
            rotation.previous_root_public_key,
            rotation.signature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid root rotation signature",
        )


def require_valid_node_delegation(
    node: Node,
    *,
    existing: StoredNode | None,
    stored_manifest: StoredManifest | None,
    required_capability: DelegationCapability,
) -> None:
    if node.delegation is None:
        if stored_manifest is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This node_id is protected by a root manifest",
            )
        if existing and existing.node.delegation:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This node_id is protected by a root delegation",
            )
        return

    if not node.node_public_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delegated announcements require node_public_key",
        )

    require_active_delegation(
        node.delegation,
        field_name="delegation.issued_at",
        required_capability=required_capability,
    )

    try:
        valid = verify_payload(
            delegation_payload(node),
            node.delegation.root_public_key,
            node.delegation.signature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid node delegation signature",
        )

    if stored_manifest is not None:
        entry = manifest_key_for_node(manifest=stored_manifest.manifest, node=node)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="node announcement does not match current node manifest",
            )
        require_manifest_key_state(
            entry,
            field_name="manifest.keys[].expires_at",
            required_capability=required_capability,
        )
    elif existing and existing.node.delegation:
        if node.delegation.root_public_key != existing.node.delegation.root_public_key:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="root_public_key does not match existing delegated node identity",
            )


def require_valid_registry_source_snapshot(payload: RegistrySourceSnapshot) -> bool:
    if payload.registry_version != PROTOCOL_VERSION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported registry_version: {payload.registry_version}",
        )

    seen_node_ids: set[str] = set()
    for item in payload.nodes:
        if item.node.node_id in seen_node_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registry source snapshot must not repeat node_id values",
            )
        seen_node_ids.add(item.node.node_id)

    exported_at = payload.exported_at.astimezone(timezone.utc)
    require_not_too_far_in_future(exported_at, field_name="exported_at")

    has_public_key = payload.registry_public_key is not None
    has_signature = payload.signature is not None
    if has_public_key != has_signature:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="registry_public_key and signature must either both be present or both be absent",
        )

    if not has_public_key and not has_signature:
        if is_loopback_url(payload.registry_url):
            return False
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Public registry source import requires registry signature",
        )

    assert payload.registry_public_key is not None
    assert payload.signature is not None
    try:
        valid = verify_payload(
            payload.model_dump(mode="json", exclude_none=True),
            payload.registry_public_key,
            payload.signature,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid registry source signature",
        )
    return True


def require_valid_registry_source(payload: RegistrySourceResponse) -> bool:
    verified_signature = require_valid_registry_source_snapshot(payload)
    exported_at = payload.exported_at.astimezone(timezone.utc)
    seen_mirrored_source_urls: set[str] = set()

    if payload.mirrored_sources and not verified_signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Re-exported mirrored sources require a verified relay signature",
        )

    if (
        payload.export_scope == "local_plus_trusted_mirrors"
        and not payload.registry_metadata.capabilities.can_reexport_sources
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Registry source export_scope=local_plus_trusted_mirrors requires can_reexport_sources capability",
        )

    if payload.mirrored_sources and payload.export_scope != "local_plus_trusted_mirrors":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mirrored source re-export requires export_scope=local_plus_trusted_mirrors",
        )

    for mirrored_source in payload.mirrored_sources or []:
        mirrored_source_url = normalized_registry_url(mirrored_source.snapshot.registry_url)
        if mirrored_source_url in seen_mirrored_source_urls:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Re-exported mirrored sources must not repeat the same registry_url",
            )
        if mirrored_source_url == normalized_registry_url(payload.registry_url):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Re-exported mirrored sources must not point back to the relay registry_url itself",
            )
        seen_mirrored_source_urls.add(mirrored_source_url)
        require_not_too_far_in_future(
            mirrored_source.imported_at,
            field_name="mirrored_sources[].imported_at",
        )
        if mirrored_source.imported_at < mirrored_source.snapshot.exported_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Re-exported mirrored source imported_at cannot be earlier than nested exported_at",
            )
        if mirrored_source.imported_at > exported_at:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Re-exported mirrored source imported_at cannot be later than top-level exported_at",
            )
        if not mirrored_source.verified_signature:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Re-exported mirrored source must carry a verified upstream signature",
            )
        nested_verified_signature = require_valid_registry_source_snapshot(mirrored_source.snapshot)
        if not nested_verified_signature:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Re-exported mirrored source must carry a verified upstream signature",
            )
        if not mirrored_source.discovery_eligible or mirrored_source.discovery_basis != "trusted_upstream":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only trusted upstream mirrored sources may be re-exported",
            )
        if (
            normalized_registry_url(mirrored_source.relayed_by_registry_url)
            != normalized_registry_url(payload.registry_url)
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Re-exported mirrored source must declare the current registry as relay",
            )
        if mirrored_source.snapshot.export_scope != "local_only":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nested mirrored source snapshots must keep export_scope=local_only",
            )

    return verified_signature


def require_allowed_unsigned_registry_source_import(
    *,
    verified_signature: bool,
    config: RegistryConfig,
) -> None:
    if verified_signature:
        return
    importer_is_local_reference = (
        config.registry_metadata.registry_type == "local"
        and (not config.registry_url or is_loopback_registry_url(config.registry_url))
    )
    if importer_is_local_reference:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Unsigned loopback registry sources are only allowed for local loopback reference development",
    )


def require_allowed_announcement_update(
    node: Node,
    existing: StoredNode | None,
    *,
    store: RegistryStore,
) -> None:
    stored_manifest = store.get_manifest(node.node_id)

    if node.delegation and not has_node_signature_fields(node):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Delegated announcements require node_public_key, signed_at, and signature",
        )

    if has_node_signature_fields(node) or node.delegation:
        require_valid_node_signature(node)
        assert node.signed_at is not None
        signed_at = parse_timestamp(node.signed_at, field_name="signed_at")
        require_monotonic_signed_event(signed_at=signed_at, stored=existing, field_name="signed_at")
        require_valid_node_delegation(
            node,
            existing=existing,
            stored_manifest=stored_manifest,
            required_capability="announce",
        )

    if existing is None:
        return

    existing_public_key = existing.node.node_public_key
    if not existing_public_key:
        return

    if not node.node_public_key or not node.signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This node_id is protected by a signing key",
        )
    if node.node_public_key != existing_public_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="node_public_key does not match existing node identity",
        )


def require_valid_heartbeat_signature(
    payload: HeartbeatRequest,
    stored: StoredNode,
    *,
    stored_manifest: StoredManifest | None,
) -> None:
    public_key = stored.node.node_public_key
    if not public_key:
        return
    if not payload.signed_at or not payload.signature:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Signed nodes require signed heartbeat updates",
        )
    try:
        valid = verify_payload(heartbeat_payload(payload), public_key, payload.signature)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid heartbeat signature",
        )
    signed_at = parse_timestamp(payload.signed_at, field_name="signed_at")
    require_monotonic_signed_event(signed_at=signed_at, stored=stored, field_name="signed_at")
    if stored.node.delegation:
        require_active_delegation(
            stored.node.delegation,
            field_name="delegation.issued_at",
            required_capability="heartbeat",
        )
    if stored_manifest is not None:
        entry = manifest_key_for_node(manifest=stored_manifest.manifest, node=stored.node)
        if entry is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Stored node announcement no longer matches current node manifest",
            )
        require_manifest_key_state(
            entry,
            field_name="manifest.keys[].expires_at",
            required_capability="heartbeat",
        )


__all__ = [
    "announcement_hash",
    "delegation_payload",
    "has_node_signature_fields",
    "heartbeat_payload",
    "identity_scope",
    "is_loopback_url",
    "manifest_key_for_node",
    "manifest_key_is_currently_active",
    "manifest_payload",
    "node_payload",
    "parse_timestamp",
    "registry_source_hash",
    "require_active_delegation",
    "require_allowed_announcement_update",
    "require_manifest_key_state",
    "require_monotonic_signed_event",
    "require_not_too_far_in_future",
    "require_registry_capability",
    "require_canonical_registry_url",
    "require_registry_signing_key",
    "require_valid_heartbeat_signature",
    "require_valid_manifest_update",
    "require_valid_node_delegation",
    "require_valid_node_signature",
    "require_valid_registry_source",
    "require_valid_registry_source_snapshot",
    "require_valid_trust_claim",
    "root_rotation_payload",
    "trust_claim_payload",
]
