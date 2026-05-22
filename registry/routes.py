from __future__ import annotations

import secrets

from fastapi import FastAPI, Header, HTTPException, Query, Request, status

from p4p_core import AnnounceResponse, HeartbeatRequest, NodeManifestRequest, RegistryEntry, utc_now
from p4p_core.constants import DEFAULT_RADIUS_KM, PROTOCOL_VERSION
from p4p_identity import sign_payload

from registry.config import RegistryConfig, normalized_registry_url
from registry.mirror import run_mirror_sync_once
from registry.models import (
    CuratedOverrideRequest,
    CuratedOverrideResponse,
    CuratedOverrideStatusResponse,
    CuratedPromotionStatusResponse,
    DirectoryClaimRequest,
    DirectoryClaimResponse,
    DirectoryClaimStatusResponse,
    DirectoryResponse,
    DiscoverResponse,
    IdentityLogResponse,
    Node,
    NodeManifestResponse,
    RegistryInfoResponse,
    RegistryMirrorStatusResponse,
    RegistrySourceImportResponse,
    RegistrySourceResponse,
    RegistrySyncResponse,
    RegistrySyncStatusResponse,
    TrustClaimImportResponse,
    TrustClaimIssueRequest,
    TrustClaimRecord,
    TrustClaimResponse,
    TrustClaimStatusResponse,
)
from registry.store import MirrorSyncState, RegistryStore
from registry.validation import (
    require_allowed_unsigned_registry_source_import,
    require_allowed_announcement_update,
    require_canonical_registry_url,
    require_registry_capability,
    require_registry_signing_key,
    require_valid_heartbeat_signature,
    require_valid_manifest_update,
    require_valid_registry_source,
)


def bind_routes(
    app: FastAPI,
    *,
    config: RegistryConfig,
    store: RegistryStore,
    mirror_sync_state: MirrorSyncState,
) -> dict[str, object]:
    def header_value(raw: object) -> str | None:
        if raw is None or not isinstance(raw, str):
            return None
        value = raw.strip()
        return value or None

    def require_registry_admin_token(
        authorization: str | None = None,
        x_p4p_registry_token: str | None = None,
    ) -> None:
        if not config.registry_admin_token:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Registry admin token is not configured",
            )
        token = header_value(x_p4p_registry_token) or ""
        bearer = header_value(authorization) or ""
        if bearer.lower().startswith("bearer "):
            token = bearer[7:].strip()
        if not token or not secrets.compare_digest(token, config.registry_admin_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid registry admin token",
            )

    @app.get("/health")
    def health() -> dict[str, object]:
        now = utc_now()
        active_mirrors = store._active_mirror_sources(now=now)
        discoverable_mirrors = store._discoverable_mirror_sources(now=now)
        store._refresh_curated_active_index(now=now)
        promotion_counts = store.curated_promotion_counts()
        override_counts = store.curated_override_counts()
        directory_counts = store.directory_claim_counts()
        trust_claim_counts = store.trust_claim_counts()
        reexportable_mirrors = [
            stored
            for stored, discovery_basis in discoverable_mirrors.values()
            if discovery_basis == "trusted_upstream" and stored.verified_signature
        ]
        return {
            "status": "ok",
            "protocol_version": PROTOCOL_VERSION,
            "registered_nodes": len(store._nodes),
            "mirrored_registries": len(active_mirrors),
            "mirrored_nodes": sum(len(stored.snapshot.nodes) for stored in active_mirrors.values()),
            "discoverable_mirrored_registries": len(discoverable_mirrors),
            "discoverable_mirrored_nodes": sum(
                len(stored.snapshot.nodes) for stored, _ in discoverable_mirrors.values()
            ),
            "configured_mirror_upstreams": len(config.mirror_upstreams),
            "trusted_mirror_upstreams": len(config.mirror_trusted_upstreams),
            "mirror_discovery_policy": config.mirror_discovery_policy,
            "curated_index_promotion_policy": config.curated_index_promotion_policy,
            "registry_source_reexport_policy": config.registry_source_reexport_policy,
            "registry_metadata": config.registry_metadata.model_dump(mode="json", exclude_none=True),
            "curated_active_index_entries": len(store._curated_active_index),
            "curated_promotion_records": promotion_counts["records"],
            "curated_promoted_sources": promotion_counts["promoted"],
            "curated_denied_sources": promotion_counts["denied"],
            "curated_override_records": override_counts["records"],
            "active_curated_overrides": override_counts["active"],
            "directory_claim_records": directory_counts["records"],
            "active_directory_claims": directory_counts["active"],
            "trust_claim_records": trust_claim_counts["records"],
            "active_trust_claims": trust_claim_counts["active"],
            "reexportable_mirrored_registries": len(reexportable_mirrors),
            "mirror_sync_interval_seconds": config.mirror_sync_interval_seconds,
            "mirror_ttl_seconds": config.mirror_source_ttl_seconds,
            "storage_backend": store.storage_backend,
            "persistence_enabled": store.persistence_enabled,
            "registry_signing_enabled": bool(config.registry_private_key),
        }

    @app.post("/announce", response_model=AnnounceResponse)
    def announce(node: Node) -> AnnounceResponse:
        require_registry_capability(
            config.registry_metadata.capabilities.can_onboard_nodes,
            detail="This registry is not allowed to onboard nodes",
        )
        if node.protocol_version != PROTOCOL_VERSION:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported protocol_version: {node.protocol_version}",
            )
        existing = store.get(node.node_id)
        require_allowed_announcement_update(node, existing, store=store)
        store.announce(node)
        return AnnounceResponse(node_id=node.node_id)

    @app.post("/node-manifest", response_model=NodeManifestResponse)
    def node_manifest(payload: NodeManifestRequest) -> NodeManifestResponse:
        require_valid_manifest_update(payload, existing=store.get_manifest(payload.manifest.node_id))
        stored = store.store_manifest(payload)
        return NodeManifestResponse(
            node_id=stored.manifest.node_id,
            manifest_version=stored.manifest.manifest_version,
        )

    @app.post("/heartbeat", response_model=AnnounceResponse)
    def heartbeat(payload: HeartbeatRequest) -> AnnounceResponse:
        stored = store.get(payload.node_id)
        if stored is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Unknown node_id: {payload.node_id}",
            )
        require_valid_heartbeat_signature(
            payload,
            stored,
            stored_manifest=store.get_manifest(payload.node_id),
        )
        stored = store.heartbeat(payload)
        assert stored is not None
        return AnnounceResponse(node_id=payload.node_id)

    @app.get("/discover", response_model=DiscoverResponse)
    def discover(
        lat: float = Query(ge=-90, le=90),
        lng: float = Query(ge=-180, le=180),
        radius: float = Query(default=DEFAULT_RADIUS_KM, gt=0),
        category: str | None = None,
        country: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
    ) -> DiscoverResponse:
        nodes = store.discover(lat=lat, lng=lng, radius=radius, category=category, country=country)
        return DiscoverResponse(nodes=nodes, query_time=utc_now())

    @app.get("/directory", response_model=DirectoryResponse)
    def directory(
        lat: float = Query(ge=-90, le=90),
        lng: float = Query(ge=-180, le=180),
        radius: float = Query(default=DEFAULT_RADIUS_KM, gt=0),
        category: str | None = None,
        country: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
    ) -> DirectoryResponse:
        nodes = store.directory(lat=lat, lng=lng, radius=radius, category=category, country=country)
        return DirectoryResponse(nodes=nodes, query_time=utc_now(), registry_metadata=config.registry_metadata)

    @app.get("/identity-log", response_model=IdentityLogResponse)
    def identity_log() -> IdentityLogResponse:
        return store.identity_log()

    @app.get("/registry-source", response_model=RegistrySourceResponse)
    def registry_source(request: Request) -> RegistrySourceResponse:
        if config.registry_source_reexport_policy != "local_only":
            require_registry_capability(
                config.registry_metadata.capabilities.can_reexport_sources,
                detail="This registry is not allowed to re-export sources",
            )
        if config.registry_private_key:
            registry_url = require_canonical_registry_url(
                config,
                detail="Signed registry source export requires P4P_REGISTRY_URL",
            )
        else:
            registry_url = config.registry_url or str(request.base_url).rstrip("/")
        snapshot = store.export_source(registry_url=registry_url)
        payload = snapshot.model_dump(mode="json", exclude_none=True)
        payload["registry_public_key"] = config.registry_public_key
        if config.registry_private_key:
            payload["signature"] = sign_payload(payload, config.registry_private_key)
        return RegistrySourceResponse(**payload)

    @app.post("/registry-source/import", response_model=RegistrySourceImportResponse)
    def registry_source_import(
        payload: RegistrySourceResponse,
        request: Request = None,
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> RegistrySourceImportResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        local_registry_url = config.registry_url
        if not local_registry_url and request is not None:
            local_registry_url = str(request.base_url).rstrip("/")
        if local_registry_url and (
            normalized_registry_url(payload.registry_url) == normalized_registry_url(local_registry_url)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Registry cannot import its own source snapshot",
            )
        require_registry_capability(
            config.registry_metadata.capabilities.can_relay_sources,
            detail="This registry is not allowed to relay upstream sources",
        )
        verified_signature = require_valid_registry_source(payload)
        require_allowed_unsigned_registry_source_import(
            verified_signature=verified_signature,
            config=config,
        )
        return store.import_source(payload, verified_signature=verified_signature)

    @app.get("/registry-mirrors", response_model=RegistryMirrorStatusResponse)
    def registry_mirrors(
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> RegistryMirrorStatusResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        return store.mirror_status()

    @app.get("/curated-promotions", response_model=CuratedPromotionStatusResponse)
    def curated_promotions(
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> CuratedPromotionStatusResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        return store.curated_promotion_status()

    @app.get("/curated-overrides", response_model=CuratedOverrideStatusResponse)
    def curated_overrides(
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> CuratedOverrideStatusResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        return store.curated_override_status()

    @app.post("/curated-overrides", response_model=CuratedOverrideResponse)
    def curated_override(
        payload: CuratedOverrideRequest,
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> CuratedOverrideResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        require_registry_capability(
            config.registry_metadata.capabilities.can_curate_active_index,
            detail="This registry is not allowed to curate a discoverable active index",
        )
        return CuratedOverrideResponse(override=store.set_curated_override(payload))

    @app.get("/directory-claims", response_model=DirectoryClaimStatusResponse)
    def directory_claims(
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> DirectoryClaimStatusResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        return store.directory_claim_status()

    @app.post("/directory-claims", response_model=DirectoryClaimResponse)
    def directory_claim(
        payload: DirectoryClaimRequest,
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> DirectoryClaimResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        require_registry_capability(
            config.registry_metadata.capabilities.can_moderate_directory,
            detail="This registry is not allowed to moderate a public directory",
        )
        return DirectoryClaimResponse(record=store.set_directory_claim(payload))

    @app.get("/trust-claims", response_model=TrustClaimStatusResponse)
    def trust_claims(
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> TrustClaimStatusResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        return store.trust_claim_status()

    @app.post("/trust-claims", response_model=TrustClaimResponse)
    def trust_claim_issue(
        payload: TrustClaimIssueRequest,
        request: Request,
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> TrustClaimResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        require_registry_capability(
            config.registry_metadata.capabilities.can_issue_trust_claims,
            detail="This registry is not allowed to issue signed trust claims",
        )
        registry_private_key, registry_public_key = require_registry_signing_key(config)
        issuer_registry_url = require_canonical_registry_url(
            config,
            detail="Signed trust claim issuance requires P4P_REGISTRY_URL",
        )
        return TrustClaimResponse(
            claim=store.issue_trust_claim(
                payload,
                issuer_registry_url=issuer_registry_url,
                issuer_registry_public_key=registry_public_key,
                issuer_private_key=registry_private_key,
            )
        )

    @app.post("/trust-claims/import", response_model=TrustClaimImportResponse)
    def trust_claim_import(
        payload: TrustClaimRecord,
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> TrustClaimImportResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        require_registry_capability(
            config.registry_metadata.capabilities.can_moderate_directory,
            detail="This registry is not allowed to project trust claims into a moderated directory",
        )
        local_payload = TrustClaimRecord(**payload.model_dump(mode="json", exclude_none=True))
        return store.import_trust_claim(local_payload)

    @app.post("/registry-sync", response_model=RegistrySyncResponse)
    async def registry_sync(
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> RegistrySyncResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        return await run_mirror_sync_once(
            config=config,
            store=store,
            mirror_sync_state=mirror_sync_state,
        )

    @app.get("/registry-sync", response_model=RegistrySyncStatusResponse)
    def registry_sync_status(
        authorization: str | None = Header(default=None),
        x_p4p_registry_token: str | None = Header(default=None),
    ) -> RegistrySyncStatusResponse:
        require_registry_admin_token(authorization, x_p4p_registry_token)
        return mirror_sync_state.snapshot()

    @app.get("/registry-info", response_model=RegistryInfoResponse)
    def registry_info(request: Request) -> RegistryInfoResponse:
        registry_url = config.registry_url or str(request.base_url).rstrip("/")
        backups = config.backup_registries or [RegistryEntry(tier=0, url=registry_url)]
        return RegistryInfoResponse(
            registry_url=registry_url,
            backups=backups,
        )

    return {
        "health": health,
        "announce": announce,
        "node_manifest": node_manifest,
        "heartbeat": heartbeat,
        "discover": discover,
        "directory": directory,
        "identity_log": identity_log,
        "registry_source": registry_source,
        "registry_source_import": registry_source_import,
        "registry_mirrors": registry_mirrors,
        "curated_promotions": curated_promotions,
        "curated_overrides": curated_overrides,
        "curated_override": curated_override,
        "directory_claims": directory_claims,
        "directory_claim": directory_claim,
        "trust_claims": trust_claims,
        "trust_claim_issue": trust_claim_issue,
        "trust_claim_import": trust_claim_import,
        "registry_sync": registry_sync,
        "registry_sync_status": registry_sync_status,
        "registry_info": registry_info,
    }


__all__ = ["bind_routes"]
