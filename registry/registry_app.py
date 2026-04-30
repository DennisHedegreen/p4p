from __future__ import annotations

import sqlite3
import sys
from datetime import timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

P4P_ROOT = Path(__file__).resolve().parents[1]
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))

from p4p_core import (
    AnnounceResponse,
    HeartbeatRequest,
    Location,
    NodeDelegation,
    NodeDescriptor,
    NodeManifest,
    NodeManifestKey,
    NodeManifestRequest,
    NodeRootRotation,
    RegistryEntry,
    build_cors_middleware_options,
    utc_now,
)
from p4p_core.constants import PROTOCOL_VERSION

from registry.config import (
    RegistryConfig,
    build_registry_config,
    load_backup_registries,
    load_mirror_trusted_upstreams,
    load_mirror_upstream_list,
    load_mirror_upstreams,
    load_registry_metadata,
    load_registry_private_key,
    resolve_curated_index_promotion_policy,
    resolve_mirror_discovery_policy,
    resolve_registry_source_reexport_policy,
    resolve_trusted_mirror_upstreams,
)
from registry.mirror import (
    build_mirror_lifespan as _build_mirror_lifespan,
    run_mirror_sync_once as _run_mirror_sync_once,
    sync_registry_source_from_upstream as _sync_registry_source_from_upstream,
)
from registry.models import (
    CATEGORY_PATTERN,
    CuratedActiveIndexEntry,
    CuratedIndexPromotionPolicy,
    CuratedOverrideDecision,
    CuratedOverrideRecord,
    CuratedOverrideRequest,
    CuratedOverrideResponse,
    CuratedOverrideStatusResponse,
    CuratedPromotionDecision,
    CuratedPromotionDecisionOrigin,
    CuratedPromotionRecord,
    CuratedPromotionStatusResponse,
    DirectoryClaim,
    DirectoryClaimRecord,
    DirectoryClaimRequest,
    DirectoryClaimResponse,
    DirectoryClaimStatusResponse,
    DirectoryNodeView,
    DirectoryResponse,
    DiscoverResponse,
    DiscoverySourceKind,
    FreshnessState,
    IdentityEventType,
    IdentityLogResponse,
    IdentityScope,
    IdentityStatus,
    MirrorDiscoveryPolicy,
    MirrorSyncStatus,
    MirrorUpstream,
    NODE_ID_PATTERN,
    Node,
    NodeIdentityEvent,
    NodeIdentityRecord,
    NodeManifestResponse,
    NodeView,
    RegistryCapabilities,
    RegistryExportScope,
    RegistryInfoResponse,
    RegistryMetadata,
    RegistryMirrorStatus,
    RegistryMirrorStatusResponse,
    RegistryScope,
    RegistrySourceImportResponse,
    RegistrySourceManifest,
    RegistrySourceMirrorExport,
    RegistrySourceNode,
    RegistrySourceResponse,
    RegistrySourceSnapshot,
    RegistrySyncResponse,
    RegistrySyncStatusResponse,
    RegistrySyncUpstreamResult,
    RegistryType,
    StorageBackend,
    TrustClaimImportResponse,
    TrustClaimIssueRequest,
    TrustClaimRecord,
    TrustClaimResponse,
    TrustClaimStatusResponse,
    TrustClaimType,
    haversine_km,
)
from registry.routes import bind_routes
from registry.store import (
    MirrorSyncState,
    RegistryStore,
    StoredManifest,
    StoredMirrorSource,
    StoredNode,
    curated_promotion_record_key,
    trust_claim_record_key,
)
from registry.validation import (
    announcement_hash,
    delegation_payload,
    has_node_signature_fields,
    heartbeat_payload,
    identity_scope,
    is_loopback_url,
    manifest_key_expiry,
    manifest_key_for_node,
    manifest_key_is_currently_active,
    manifest_payload,
    node_payload,
    parse_timestamp,
    registry_source_hash,
    require_active_delegation,
    require_allowed_announcement_update,
    require_manifest_key_state,
    require_monotonic_signed_event,
    require_not_too_far_in_future,
    require_registry_capability,
    require_registry_signing_key,
    require_valid_heartbeat_signature,
    require_valid_manifest_update,
    require_valid_node_delegation,
    require_valid_node_signature,
    require_valid_registry_source,
    require_valid_registry_source_snapshot,
    require_valid_trust_claim,
    root_rotation_payload,
    trust_claim_payload,
)


CONFIG = build_registry_config()
REGISTRY_URL = CONFIG.registry_url
BACKUP_REGISTRIES = CONFIG.backup_registries
MIRROR_UPSTREAMS = CONFIG.mirror_upstreams
MIRROR_TRUSTED_UPSTREAMS = CONFIG.mirror_trusted_upstreams
TRUSTED_MIRROR_UPSTREAM_URLS = CONFIG.trusted_mirror_upstream_urls
MIRROR_DISCOVERY_POLICY = CONFIG.mirror_discovery_policy
REGISTRY_SOURCE_REEXPORT_POLICY = CONFIG.registry_source_reexport_policy
CURATED_INDEX_PROMOTION_POLICY = CONFIG.curated_index_promotion_policy
MIRROR_SYNC_INTERVAL_SECONDS = CONFIG.mirror_sync_interval_seconds
MIRROR_SOURCE_TTL_SECONDS = CONFIG.mirror_source_ttl_seconds
REGISTRY_PRIVATE_KEY = CONFIG.registry_private_key
REGISTRY_PUBLIC_KEY = CONFIG.registry_public_key
REGISTRY_METADATA = CONFIG.registry_metadata
REGISTRY_DB_PATH = CONFIG.registry_db_path

store = RegistryStore(db_path=REGISTRY_DB_PATH, config=CONFIG)
MIRROR_SYNC_STATE = MirrorSyncState(config=CONFIG, store=store)

app = FastAPI(
    title="P4P Registry",
    version=PROTOCOL_VERSION,
    summary="Reference registry for the P4P v0.1 protocol.",
    lifespan=_build_mirror_lifespan(
        config=CONFIG,
        store=store,
        mirror_sync_state=MIRROR_SYNC_STATE,
    ),
)
app.add_middleware(CORSMiddleware, **build_cors_middleware_options())


async def sync_registry_source_from_upstream(upstream, client):
    return await _sync_registry_source_from_upstream(
        upstream,
        client,
        config=CONFIG,
        store=store,
    )


async def run_mirror_sync_once():
    return await _run_mirror_sync_once(
        config=CONFIG,
        store=store,
        mirror_sync_state=MIRROR_SYNC_STATE,
    )

globals().update(
    bind_routes(
        app,
        config=CONFIG,
        store=store,
        mirror_sync_state=MIRROR_SYNC_STATE,
    )
)
