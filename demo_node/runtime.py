from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any

from p4p_core import (
    Location,
    Menu,
    MenuItem,
    NodeDelegation,
    NodeDescriptor,
    NodeManifest,
    NodeManifestKey,
    NodeManifestRequest,
    NodeRootRotation,
    RegistrationSnapshot,
    resolve_enabled_modules,
    utc_now,
)
from p4p_core.constants import DelegationCapability, DelegationRole, ManifestKeyStatus
from p4p_identity import sign_payload

from demo_node.config import DemoConfig, build_demo_config


@dataclass
class DemoRuntime:
    config: DemoConfig
    node: NodeDescriptor
    node_manifest: NodeManifest | None
    menu: Menu
    registration: RegistrationSnapshot
    heartbeat_task: asyncio.Task[None] | None = None


def delegation_payload(*, node_id: str, node_public_key: str, delegation: NodeDelegation) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "node_public_key": node_public_key,
        "root_public_key": delegation.root_public_key,
        "issued_at": delegation.issued_at,
        "expires_at": delegation.expires_at,
        "role": delegation.role,
        "capabilities": delegation.capabilities,
    }


def build_node_delegation(
    *,
    runtime: DemoRuntime,
    root_private_key: str | None = None,
    root_public_key: str | None = None,
    issued_at: str | None = None,
    expires_at: str | None = None,
    role: DelegationRole | None = None,
    capabilities: list[DelegationCapability] | None = None,
) -> NodeDelegation | None:
    effective_root_private_key = root_private_key or runtime.config.root_private_key
    effective_root_public_key = root_public_key or runtime.config.root_public_key

    if not effective_root_private_key or not effective_root_public_key:
        return None

    delegation_data: dict[str, Any] = {
        "root_public_key": effective_root_public_key,
        "issued_at": issued_at
        or (os.environ.get("P4P_NODE_DELEGATION_ISSUED_AT", "").strip() or utc_now().isoformat()),
        "expires_at": expires_at
        if expires_at is not None
        else (os.environ.get("P4P_NODE_DELEGATION_EXPIRES_AT", "").strip() or None),
        "role": role or os.environ.get("P4P_NODE_DELEGATION_ROLE", "primary").strip() or "primary",
        "capabilities": capabilities or [
            value.strip()
            for value in os.environ.get("P4P_NODE_DELEGATION_CAPABILITIES", "announce,heartbeat").split(",")
            if value.strip()
        ],
    }
    unsigned_delegation = NodeDelegation(signature="ed25519:placeholder", **delegation_data)
    delegation_data["signature"] = sign_payload(
        delegation_payload(
            node_id=runtime.node.node_id,
            node_public_key=runtime.config.node_public_key,
            delegation=unsigned_delegation,
        ),
        effective_root_private_key,
    )
    return NodeDelegation(**delegation_data)


def node_manifest_payload(*, manifest: NodeManifest) -> dict[str, Any]:
    return {
        "node_id": manifest.node_id,
        "root_public_key": manifest.root_public_key,
        "manifest_version": manifest.manifest_version,
        "issued_at": manifest.issued_at,
        "keys": [entry.model_dump(mode="json", exclude_none=True) for entry in manifest.keys],
    }


def root_rotation_payload(*, rotation: NodeRootRotation) -> dict[str, Any]:
    return {
        "node_id": rotation.node_id,
        "previous_root_public_key": rotation.previous_root_public_key,
        "next_root_public_key": rotation.next_root_public_key,
        "rotated_at": rotation.rotated_at,
    }


def build_node_manifest(
    *,
    runtime: DemoRuntime,
    root_private_key: str | None = None,
    root_public_key: str | None = None,
    node_public_key: str | None = None,
    manifest_version: int | None = None,
    issued_at: str | None = None,
    key_status: ManifestKeyStatus | None = None,
    key_expires_at: str | None = None,
    role: DelegationRole | None = None,
    capabilities: list[DelegationCapability] | None = None,
) -> NodeManifest | None:
    effective_root_private_key = root_private_key or runtime.config.root_private_key
    effective_root_public_key = root_public_key or runtime.config.root_public_key
    effective_node_public_key = node_public_key or runtime.config.node_public_key

    if not effective_root_private_key or not effective_root_public_key:
        return None

    manifest_key = NodeManifestKey(
        node_public_key=effective_node_public_key,
        role=role or (runtime.node.delegation.role if runtime.node.delegation else "primary"),
        capabilities=capabilities
        or (runtime.node.delegation.capabilities if runtime.node.delegation else ["announce", "heartbeat"]),
        status=key_status or (os.environ.get("P4P_NODE_MANIFEST_KEY_STATUS", "active").strip() or "active"),
        expires_at=(
            key_expires_at
            if key_expires_at is not None
            else (os.environ.get("P4P_NODE_MANIFEST_KEY_EXPIRES_AT", "").strip() or None)
        )
        or (runtime.node.delegation.expires_at if runtime.node.delegation else None),
    )
    manifest_data: dict[str, Any] = {
        "node_id": runtime.node.node_id,
        "root_public_key": effective_root_public_key,
        "manifest_version": manifest_version
        if manifest_version is not None
        else int(os.environ.get("P4P_NODE_MANIFEST_VERSION", "1").strip() or "1"),
        "issued_at": issued_at
        if issued_at is not None
        else (
            os.environ.get("P4P_NODE_MANIFEST_ISSUED_AT", "").strip()
            or (runtime.node.delegation.issued_at if runtime.node.delegation else utc_now().isoformat())
        ),
        "keys": [manifest_key.model_dump(mode="json", exclude_none=True)],
    }
    unsigned_manifest = NodeManifest(signature="ed25519:placeholder", **manifest_data)
    manifest_data["signature"] = sign_payload(
        node_manifest_payload(manifest=unsigned_manifest),
        effective_root_private_key,
    )
    return NodeManifest(**manifest_data)


def build_root_rotation(
    *,
    runtime: DemoRuntime,
    previous_root_private_key: str,
    previous_root_public_key: str,
    next_root_public_key: str,
    rotated_at: str | None = None,
) -> NodeRootRotation:
    rotation_data: dict[str, Any] = {
        "node_id": runtime.node.node_id,
        "previous_root_public_key": previous_root_public_key,
        "next_root_public_key": next_root_public_key,
        "rotated_at": rotated_at or utc_now().isoformat(),
    }
    unsigned_rotation = NodeRootRotation(signature="ed25519:placeholder", **rotation_data)
    rotation_data["signature"] = sign_payload(
        root_rotation_payload(rotation=unsigned_rotation),
        previous_root_private_key,
    )
    return NodeRootRotation(**rotation_data)


def signed_node_manifest_request(
    *,
    runtime: DemoRuntime,
    manifest: NodeManifest | None = None,
    root_rotation: NodeRootRotation | None = None,
) -> dict[str, Any] | None:
    effective_manifest = manifest or runtime.node_manifest
    if effective_manifest is None:
        return None
    payload = NodeManifestRequest(manifest=effective_manifest, root_rotation=root_rotation)
    return payload.model_dump(mode="json", exclude_none=True)


def node_accepts_orders(runtime: DemoRuntime) -> bool:
    return runtime.node.order_mode in {"test", "live"}


def sign_node_announcement(runtime: DemoRuntime) -> dict[str, Any]:
    runtime.node.node_public_key = runtime.config.node_public_key
    runtime.node.signed_at = utc_now().isoformat()
    runtime.node.signature = None
    payload = runtime.node.model_dump(mode="json", exclude_none=True)
    runtime.node.signature = sign_payload(payload, runtime.config.node_private_key)
    return runtime.node.model_dump(mode="json", exclude_none=True)


def signed_heartbeat_payload(runtime: DemoRuntime) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "node_id": runtime.node.node_id,
        "open": runtime.node.open,
        "signed_at": utc_now().isoformat(),
    }
    payload["signature"] = sign_payload(payload, runtime.config.node_private_key)
    return payload


def registration_payload(runtime: DemoRuntime) -> dict[str, Any]:
    return {
        "ready": runtime.registration.ready(),
        "configured_registries": runtime.registration.configured_registries,
        "registered_registries": runtime.registration.registered_registries,
        "failed_registries": runtime.registration.failed_registries,
        "last_cycle_finished_at": runtime.registration.last_cycle_finished_at.isoformat()
        if runtime.registration.last_cycle_finished_at
        else None,
    }


def operator_state_payload(runtime: DemoRuntime) -> dict[str, Any]:
    resolved_modules = resolve_enabled_modules(runtime.node.modules, strict=False)
    declared_module_ids = set(resolved_modules.module_ids)
    undeclared_modules = [module_id for module_id in runtime.node.modules if module_id not in declared_module_ids]
    return {
        "node": runtime.node.model_dump(mode="json"),
        "accepts_orders": node_accepts_orders(runtime),
        "identity": {
            "key_type": "ed25519",
            "node_public_key": runtime.config.node_public_key,
            "root_public_key": runtime.config.root_public_key,
            "delegation_role": runtime.node.delegation.role if runtime.node.delegation else None,
            "manifest_version": runtime.node_manifest.manifest_version if runtime.node_manifest else None,
            "manifest_key_status": runtime.node_manifest.keys[0].status if runtime.node_manifest else None,
            "signed_announcements": True,
        },
        "available_order_modes": list(runtime.config.order_modes),
        "available_modules": sorted(set(runtime.config.reference_modules).union(runtime.node.modules)),
        "enabled_modules": list(runtime.node.modules),
        "public_modules": list(runtime.node.modules),
        "module_declarations": resolved_modules.declarations(),
        "public_module_declarations": resolved_modules.public_declarations(),
        "undeclared_modules": undeclared_modules,
        "registry": registration_payload(runtime),
    }


def public_module_projection(runtime: DemoRuntime) -> dict[str, Any]:
    state = operator_state_payload(runtime)
    return {
        "modules": list(state["public_modules"]),
        "module_declarations": list(state["public_module_declarations"]),
        "undeclared_modules": list(state["undeclared_modules"]),
    }


def build_demo_runtime(config: DemoConfig | None = None) -> DemoRuntime:
    effective_config = config or build_demo_config()
    runtime = DemoRuntime(
        config=effective_config,
        node=NodeDescriptor(
            node_id=effective_config.node_id,
            name=effective_config.node_name,
            location=Location(lat=effective_config.node_lat, lng=effective_config.node_lng),
            country=effective_config.node_country,
            city=effective_config.node_city,
            categories=effective_config.node_categories,
            endpoint=f"{effective_config.node_base_url.rstrip('/')}/p4p",
            open=effective_config.node_open,
            order_mode=effective_config.node_order_mode,
            modules=effective_config.node_modules,
            node_public_key=effective_config.node_public_key,
        ),
        node_manifest=None,
        menu=Menu(
            updated_at=utc_now(),
            items=[
                MenuItem(
                    id=effective_config.menu_item_1_id,
                    name=effective_config.menu_item_1_name,
                    description=effective_config.menu_item_1_description,
                    price=effective_config.menu_item_1_price,
                    category="pizza",
                ),
                MenuItem(
                    id=effective_config.menu_item_2_id,
                    name=effective_config.menu_item_2_name,
                    description=effective_config.menu_item_2_description,
                    price=effective_config.menu_item_2_price,
                    category="pizza",
                ),
            ],
        ),
        registration=RegistrationSnapshot(
            configured_registries=effective_config.registry_urls.copy(),
            stale_after_seconds=effective_config.readiness_stale_after_seconds,
        ),
    )
    runtime.node.delegation = build_node_delegation(runtime=runtime)
    runtime.node_manifest = build_node_manifest(runtime=runtime)
    return runtime


__all__ = [
    "DemoRuntime",
    "build_demo_runtime",
    "build_node_delegation",
    "build_node_manifest",
    "build_root_rotation",
    "delegation_payload",
    "node_accepts_orders",
    "node_manifest_payload",
    "operator_state_payload",
    "public_module_projection",
    "registration_payload",
    "root_rotation_payload",
    "sign_node_announcement",
    "signed_heartbeat_payload",
    "signed_node_manifest_request",
]
