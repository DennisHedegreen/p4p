from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from p4p_core import NodeDescriptor, NodeManifest, NodeModuleDeclaration, RegistryEntry
from p4p_core.constants import CATEGORY_PATTERN, NODE_ID_PATTERN, PROTOCOL_VERSION


IdentityEventType = Literal["signed_announcement"]
IdentityScope = Literal["loopback", "public"]
IdentityStatus = Literal["active", "revoked", "rotated"]
StorageBackend = Literal["memory", "sqlite"]
DiscoverySourceKind = Literal["local", "mirrored"]
RegistryExportScope = Literal["local_only", "local_plus_trusted_mirrors"]
MirrorDiscoveryPolicy = Literal["trusted_only", "all_active"]
RegistryType = Literal["umbrella", "vertical", "country", "local"]
CuratedIndexPromotionPolicy = Literal["manual_only", "trusted_mirrors"]
FreshnessState = Literal["fresh", "stale"]
CuratedPromotionDecision = Literal["promote", "deny"]
CuratedPromotionDecisionOrigin = Literal["automatic", "manual"]
CuratedOverrideDecision = Literal["allow", "deny"]
DirectoryClaim = Literal["reviewed", "verified", "hidden", "spam", "local_only"]
TrustClaimType = Literal["reviewed", "verified"]
MirrorSyncStatus = Literal["imported", "skipped", "error"]


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    from math import asin, cos, radians, sin, sqrt

    radius_km = 6371.0
    lat1_rad = radians(lat1)
    lng1_rad = radians(lng1)
    lat2_rad = radians(lat2)
    lng2_rad = radians(lng2)

    delta_lat = lat2_rad - lat1_rad
    delta_lng = lng2_rad - lng1_rad

    a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lng / 2) ** 2
    c = 2 * asin(sqrt(a))
    return radius_km * c


NodeBase = NodeDescriptor


class Node(NodeBase):
    pass


class NodeView(NodeBase):
    last_seen: datetime
    distance_km: float | None = Field(default=None, ge=0)
    source_kind: DiscoverySourceKind = Field(default="local")
    source_registry_url: HttpUrl | None = None
    source_relay_registry_url: HttpUrl | None = None
    source_signature_verified: bool | None = None
    source_discovery_basis: str | None = None
    source_snapshot_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    source_exported_at: datetime | None = None
    source_imported_at: datetime | None = None
    source_last_synced_at: datetime | None = None
    source_freshness_state: FreshnessState | None = None


class DirectoryNodeView(NodeView):
    directory_claims: list[DirectoryClaim] = Field(default_factory=list)
    directory_reason: str | None = None
    directory_set_by: str | None = None
    directory_expires_at: datetime | None = None
    directory_set_at: datetime | None = None
    module_declarations: list[NodeModuleDeclaration] = Field(default_factory=list)
    undeclared_modules: list[str] = Field(default_factory=list)
    trust_claims: list[TrustClaimType] = Field(default_factory=list)
    trust_claim_issuers: list[HttpUrl] = Field(default_factory=list)


class DiscoverResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[NodeView]
    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime


class MirrorUpstream(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: HttpUrl


class RegistryCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    can_onboard_nodes: bool = True
    can_relay_sources: bool = True
    can_curate_active_index: bool = False
    can_moderate_directory: bool = False
    can_issue_trust_claims: bool = False
    can_reexport_sources: bool = False


class RegistryScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vertical_id: str | None = None
    country_code: str | None = Field(default=None, pattern=r"^[A-Z]{2}$")
    locality_id: str | None = None


class RegistryMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_type: RegistryType = Field(default="local")
    capabilities: RegistryCapabilities = Field(default_factory=RegistryCapabilities)
    scope: RegistryScope = Field(default_factory=RegistryScope)
    delegated_by_registry_url: HttpUrl | None = None


class DirectoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[DirectoryNodeView]
    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime
    registry_metadata: RegistryMetadata


class RegistryInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    registry_url: HttpUrl
    backups: list[RegistryEntry]


class NodeManifestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    manifest_version: int = Field(ge=1)


class NodeIdentityEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: int = Field(ge=1)
    event_type: IdentityEventType = Field(default="signed_announcement")
    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    node_public_key: str = Field(pattern=r"^ed25519:")
    signed_at: str = Field(min_length=1)
    announcement_signature: str = Field(pattern=r"^ed25519:")
    announcement_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: IdentityStatus = Field(default="active")
    scope: IdentityScope
    recorded_at: datetime


class NodeIdentityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    node_public_key: str = Field(pattern=r"^ed25519:")
    first_seen: datetime
    last_seen: datetime
    status: IdentityStatus = Field(default="active")
    scope: IdentityScope
    event_count: int = Field(ge=1)


class IdentityLogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime
    records: list[NodeIdentityRecord]
    events: list[NodeIdentityEvent]


class RegistrySourceNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: Node
    last_seen: datetime
    last_signed_event_at: datetime | None = None


class RegistrySourceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: NodeManifest
    stored_at: datetime


class RegistrySourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    registry_url: HttpUrl
    registry_metadata: RegistryMetadata
    export_scope: RegistryExportScope = Field(default="local_only")
    exported_at: datetime
    storage_backend: StorageBackend
    latest_identity_event_id: int | None = Field(default=None, ge=1)
    nodes: list[RegistrySourceNode]
    manifests: list[RegistrySourceManifest]
    identity_records: list[NodeIdentityRecord]
    identity_events: list[NodeIdentityEvent]
    registry_public_key: str | None = Field(default=None, pattern=r"^ed25519:")
    signature: str | None = Field(default=None, pattern=r"^ed25519:")


class RegistrySourceMirrorExport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snapshot: RegistrySourceSnapshot
    imported_at: datetime
    verified_signature: bool
    discovery_eligible: bool
    discovery_basis: str
    relayed_by_registry_url: HttpUrl


class RegistrySourceResponse(RegistrySourceSnapshot):
    mirrored_sources: list[RegistrySourceMirrorExport] | None = None


class RegistrySourceImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    registry_url: HttpUrl
    verified_signature: bool
    imported_at: datetime
    imported_nodes: int = Field(ge=0)
    imported_manifests: int = Field(ge=0)
    imported_relayed_sources: int = Field(default=0, ge=0)
    latest_identity_event_id: int | None = Field(default=None, ge=1)


class CuratedActiveIndexEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node: Node
    last_seen: datetime
    source_kind: DiscoverySourceKind = Field(default="mirrored")
    source_registry_url: HttpUrl
    source_relay_registry_url: HttpUrl | None = None
    source_signature_verified: bool
    source_discovery_basis: str
    source_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_exported_at: datetime
    source_imported_at: datetime
    source_last_synced_at: datetime
    source_freshness_state: FreshnessState = Field(default="fresh")


class CuratedPromotionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_registry_url: HttpUrl
    source_relay_registry_url: HttpUrl | None = None
    source_signature_verified: bool
    source_snapshot_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    source_exported_at: datetime
    source_imported_at: datetime
    source_last_synced_at: datetime
    source_freshness_state: FreshnessState = Field(default="fresh")
    automatic_decision: CuratedPromotionDecision
    automatic_decision_basis: str
    automatic_decision_reason: str
    override_decision: CuratedOverrideDecision | None = None
    override_reason: str | None = None
    override_set_by: str | None = None
    override_expires_at: datetime | None = None
    override_set_at: datetime | None = None
    decision: CuratedPromotionDecision
    decision_origin: CuratedPromotionDecisionOrigin
    decision_basis: str
    decision_reason: str
    active: bool
    promotion_eligible: bool
    promoted_node_ids: list[str] = Field(default_factory=list)
    decided_at: datetime
    last_evaluated_at: datetime


class CuratedPromotionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime
    registry_metadata: RegistryMetadata
    curated_index_promotion_policy: CuratedIndexPromotionPolicy
    records: list[CuratedPromotionRecord]


class CuratedOverrideRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_registry_url: HttpUrl
    source_relay_registry_url: HttpUrl | None = None
    decision: CuratedOverrideDecision
    reason: str = Field(min_length=1)
    set_by: str | None = None
    expires_at: datetime | None = None
    set_at: datetime


class CuratedOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_registry_url: HttpUrl
    source_relay_registry_url: HttpUrl | None = None
    decision: CuratedOverrideDecision
    reason: str = Field(min_length=1)
    set_by: str | None = None
    expires_at: datetime | None = None


class CuratedOverrideResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    override: CuratedOverrideRecord


class CuratedOverrideStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime
    registry_metadata: RegistryMetadata
    records: list[CuratedOverrideRecord]


class DirectoryClaimRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    claims: list[DirectoryClaim] = Field(min_length=1)
    reason: str | None = None
    set_by: str | None = None
    expires_at: datetime | None = None
    set_at: datetime

    @field_validator("claims")
    @classmethod
    def normalize_claims(cls, values: list[DirectoryClaim]) -> list[DirectoryClaim]:
        normalized: list[DirectoryClaim] = []
        seen: set[DirectoryClaim] = set()
        for value in values:
            if value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        if not normalized:
            raise ValueError("directory claims must not be empty")
        return normalized


class DirectoryClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    claims: list[DirectoryClaim] = Field(min_length=1)
    reason: str | None = None
    set_by: str | None = None
    expires_at: datetime | None = None

    @field_validator("claims")
    @classmethod
    def normalize_claims(cls, values: list[DirectoryClaim]) -> list[DirectoryClaim]:
        return DirectoryClaimRecord.normalize_claims(values)


class DirectoryClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    record: DirectoryClaimRecord


class DirectoryClaimStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime
    registry_metadata: RegistryMetadata
    records: list[DirectoryClaimRecord]


class TrustClaimRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issuer_registry_url: HttpUrl
    issuer_registry_public_key: str = Field(pattern=r"^ed25519:")
    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    claims: list[TrustClaimType] = Field(min_length=1)
    reason: str | None = None
    issued_at: datetime
    expires_at: datetime | None = None
    signature: str = Field(pattern=r"^ed25519:")

    @field_validator("claims")
    @classmethod
    def normalize_claims(cls, values: list[TrustClaimType]) -> list[TrustClaimType]:
        normalized: list[TrustClaimType] = []
        seen: set[TrustClaimType] = set()
        for value in values:
            if value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        if not normalized:
            raise ValueError("trust claims must not be empty")
        return normalized


class TrustClaimIssueRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    claims: list[TrustClaimType] = Field(min_length=1)
    reason: str | None = None
    expires_at: datetime | None = None

    @field_validator("claims")
    @classmethod
    def normalize_claims(cls, values: list[TrustClaimType]) -> list[TrustClaimType]:
        return TrustClaimRecord.normalize_claims(values)


class TrustClaimResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    claim: TrustClaimRecord


class TrustClaimStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime
    registry_metadata: RegistryMetadata
    records: list[TrustClaimRecord]


class TrustClaimImportResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    issuer_registry_url: HttpUrl
    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    imported_at: datetime


class RegistryMirrorStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_url: HttpUrl
    imported_at: datetime
    expires_at: datetime
    active: bool
    discovery_eligible: bool
    discovery_basis: str
    verified_signature: bool
    relayed_by_registry_url: HttpUrl | None = None
    imported_nodes: int = Field(ge=0)
    imported_manifests: int = Field(ge=0)
    latest_identity_event_id: int | None = Field(default=None, ge=1)


class RegistryMirrorStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime
    sources: list[RegistryMirrorStatus]


class RegistrySyncUpstreamResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_url: HttpUrl
    status: MirrorSyncStatus
    verified_signature: bool | None = None
    imported_nodes: int | None = Field(default=None, ge=0)
    imported_manifests: int | None = Field(default=None, ge=0)
    latest_identity_event_id: int | None = Field(default=None, ge=1)
    detail: str | None = None


class RegistrySyncResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    run_started_at: datetime
    run_completed_at: datetime
    upstreams: list[RegistrySyncUpstreamResult]


class RegistrySyncStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime
    registry_metadata: RegistryMetadata
    configured_upstreams: list[MirrorUpstream]
    trusted_upstreams: list[MirrorUpstream]
    mirror_discovery_policy: MirrorDiscoveryPolicy
    curated_index_promotion_policy: CuratedIndexPromotionPolicy
    curated_promotion_records: int = Field(ge=0)
    curated_promoted_sources: int = Field(ge=0)
    curated_denied_sources: int = Field(ge=0)
    curated_override_records: int = Field(ge=0)
    active_curated_overrides: int = Field(ge=0)
    sync_interval_seconds: int = Field(ge=0)
    mirror_ttl_seconds: int = Field(ge=1)
    last_run_at: datetime | None = None
    last_successful_run_at: datetime | None = None
    last_results: list[RegistrySyncUpstreamResult]


__all__ = [
    "CATEGORY_PATTERN",
    "CuratedActiveIndexEntry",
    "CuratedIndexPromotionPolicy",
    "CuratedOverrideDecision",
    "CuratedOverrideRecord",
    "CuratedOverrideRequest",
    "CuratedOverrideResponse",
    "CuratedOverrideStatusResponse",
    "CuratedPromotionDecision",
    "CuratedPromotionDecisionOrigin",
    "CuratedPromotionRecord",
    "CuratedPromotionStatusResponse",
    "DirectoryClaim",
    "DirectoryClaimRecord",
    "DirectoryClaimRequest",
    "DirectoryClaimResponse",
    "DirectoryClaimStatusResponse",
    "DirectoryNodeView",
    "DirectoryResponse",
    "DiscoverResponse",
    "DiscoverySourceKind",
    "FreshnessState",
    "IdentityEventType",
    "IdentityLogResponse",
    "IdentityScope",
    "IdentityStatus",
    "MirrorDiscoveryPolicy",
    "MirrorSyncStatus",
    "MirrorUpstream",
    "NODE_ID_PATTERN",
    "Node",
    "NodeIdentityEvent",
    "NodeIdentityRecord",
    "NodeManifestResponse",
    "NodeView",
    "PROTOCOL_VERSION",
    "RegistryCapabilities",
    "RegistryExportScope",
    "RegistryInfoResponse",
    "RegistryMetadata",
    "RegistryMirrorStatus",
    "RegistryMirrorStatusResponse",
    "RegistryScope",
    "RegistrySourceImportResponse",
    "RegistrySourceManifest",
    "RegistrySourceMirrorExport",
    "RegistrySourceNode",
    "RegistrySourceResponse",
    "RegistrySourceSnapshot",
    "RegistrySyncResponse",
    "RegistrySyncStatusResponse",
    "RegistrySyncUpstreamResult",
    "RegistryType",
    "StorageBackend",
    "TrustClaimImportResponse",
    "TrustClaimIssueRequest",
    "TrustClaimRecord",
    "TrustClaimResponse",
    "TrustClaimStatusResponse",
    "TrustClaimType",
    "haversine_km",
]
