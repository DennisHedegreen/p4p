from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

P4P_ROOT = Path(__file__).resolve().parents[1]
if str(P4P_ROOT) not in sys.path:
    sys.path.insert(0, str(P4P_ROOT))

from p4p_identity import load_or_create_private_key, public_key_from_private, sign_payload, verify_payload


PROTOCOL_VERSION = "0.1"
HEARTBEAT_TTL_SECONDS = 180
MAX_SIGNED_AT_FUTURE_SKEW_SECONDS = 30
DEFAULT_RADIUS_KM = 5.0
OrderMode = Literal["disabled", "menu_only", "test", "live"]
DelegationRole = Literal["primary", "backup"]
DelegationCapability = Literal["announce", "heartbeat"]
ManifestKeyStatus = Literal["active", "revoked"]
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
NODE_ID_PATTERN = r"^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*-\d{3,}$"
CATEGORY_PATTERN = r"^[a-z0-9][a-z0-9-]*$"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_backup_registries() -> list["RegistryEntry"]:
    raw = os.environ.get("P4P_BACKUP_REGISTRIES")
    if not raw:
        return []

    parsed = json.loads(raw)
    return [RegistryEntry(**entry) for entry in parsed]


def load_mirror_upstream_list(env_key: str) -> list["MirrorUpstream"]:
    raw = os.environ.get(env_key, "").strip()
    if not raw:
        return []

    if raw.startswith("["):
        parsed = json.loads(raw)
        values: list[MirrorUpstream] = []
        for entry in parsed:
            if isinstance(entry, str):
                values.append(MirrorUpstream(url=entry))
            else:
                values.append(MirrorUpstream(**entry))
        return values

    return [MirrorUpstream(url=value.strip()) for value in raw.split(",") if value.strip()]


def load_mirror_upstreams() -> list["MirrorUpstream"]:
    return load_mirror_upstream_list("P4P_MIRROR_UPSTREAMS")


def load_mirror_trusted_upstreams() -> list["MirrorUpstream"]:
    return load_mirror_upstream_list("P4P_MIRROR_TRUSTED_UPSTREAMS")


def resolve_mirror_discovery_policy(
    configured_upstreams: list["MirrorUpstream"],
    trusted_upstreams: list["MirrorUpstream"],
) -> MirrorDiscoveryPolicy:
    raw = os.environ.get("P4P_MIRROR_DISCOVERY_POLICY", "").strip()
    if raw:
        if raw not in {"trusted_only", "all_active"}:
            raise ValueError(
                "P4P_MIRROR_DISCOVERY_POLICY must be 'trusted_only' or 'all_active'"
            )
        return raw
    if trusted_upstreams or configured_upstreams:
        return "trusted_only"
    return "all_active"


def resolve_trusted_mirror_upstreams(
    *,
    configured_upstreams: list["MirrorUpstream"],
    explicit_trusted_upstreams: list["MirrorUpstream"],
) -> list["MirrorUpstream"]:
    source = explicit_trusted_upstreams or configured_upstreams
    deduped: list[MirrorUpstream] = []
    seen: set[str] = set()
    for upstream in source:
        normalized = normalized_registry_url(upstream.url)
        if normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(upstream)
    return deduped


def resolve_registry_source_reexport_policy() -> RegistryExportScope:
    raw = os.environ.get("P4P_REGISTRY_SOURCE_REEXPORT_POLICY", "").strip()
    if not raw:
        return "local_only"
    if raw not in {"local_only", "local_plus_trusted_mirrors"}:
        raise ValueError(
            "P4P_REGISTRY_SOURCE_REEXPORT_POLICY must be 'local_only' or 'local_plus_trusted_mirrors'"
        )
    return raw


def resolve_curated_index_promotion_policy() -> CuratedIndexPromotionPolicy:
    raw = os.environ.get("P4P_CURATED_INDEX_PROMOTION_POLICY", "").strip()
    if not raw:
        return "manual_only"
    if raw not in {"manual_only", "trusted_mirrors"}:
        raise ValueError(
            "P4P_CURATED_INDEX_PROMOTION_POLICY must be 'manual_only' or 'trusted_mirrors'"
        )
    return raw


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


class Location(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)


class NodeDelegation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_public_key: str = Field(pattern=r"^ed25519:")
    issued_at: str
    expires_at: str | None = None
    role: DelegationRole = Field(default="primary")
    capabilities: list[DelegationCapability] = Field(default_factory=lambda: ["announce", "heartbeat"])
    signature: str = Field(pattern=r"^ed25519:")

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, values: list[DelegationCapability]) -> list[DelegationCapability]:
        normalized: list[DelegationCapability] = []
        seen: set[DelegationCapability] = set()
        for value in values:
            if value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        if not normalized:
            raise ValueError("delegation capabilities must not be empty")
        return normalized


class NodeManifestKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_public_key: str = Field(pattern=r"^ed25519:")
    role: DelegationRole = Field(default="primary")
    capabilities: list[DelegationCapability] = Field(default_factory=lambda: ["announce", "heartbeat"])
    status: ManifestKeyStatus = Field(default="active")
    expires_at: str | None = None

    @field_validator("capabilities")
    @classmethod
    def normalize_capabilities(cls, values: list[DelegationCapability]) -> list[DelegationCapability]:
        normalized: list[DelegationCapability] = []
        seen: set[DelegationCapability] = set()
        for value in values:
            if value in seen:
                continue
            normalized.append(value)
            seen.add(value)
        if not normalized:
            raise ValueError("manifest key capabilities must not be empty")
        return normalized


class NodeManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    root_public_key: str = Field(pattern=r"^ed25519:")
    manifest_version: int = Field(ge=1)
    issued_at: str
    keys: list[NodeManifestKey] = Field(min_length=1)
    signature: str = Field(pattern=r"^ed25519:")

    @field_validator("keys")
    @classmethod
    def validate_keys(cls, values: list[NodeManifestKey]) -> list[NodeManifestKey]:
        seen: set[str] = set()
        for value in values:
            if value.node_public_key in seen:
                raise ValueError("manifest keys must be unique by node_public_key")
            seen.add(value.node_public_key)
        return values


class NodeRootRotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    previous_root_public_key: str = Field(pattern=r"^ed25519:")
    next_root_public_key: str = Field(pattern=r"^ed25519:")
    rotated_at: str
    signature: str = Field(pattern=r"^ed25519:")


class NodeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    name: str = Field(min_length=1)
    location: Location
    country: str = Field(pattern=r"^[A-Z]{2}$")
    city: str = Field(min_length=1)
    categories: list[str] = Field(default_factory=list)
    endpoint: HttpUrl
    open: bool
    order_mode: OrderMode = Field(default="disabled")
    modules: list[str] = Field(default_factory=list)
    node_public_key: str | None = None
    delegation: NodeDelegation | None = None
    signed_at: str | None = None
    signature: str | None = None
    protocol_version: str = Field(default=PROTOCOL_VERSION)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: HttpUrl) -> HttpUrl:
        if value.scheme == "https":
            return value
        if value.scheme == "http" and value.host in {"127.0.0.1", "localhost"}:
            return value
        raise ValueError(
            "endpoint must use https unless it is loopback http for local reference development"
        )

    @field_validator("node_public_key")
    @classmethod
    def validate_public_key(cls, value: str | None) -> str | None:
        if value is None or value.startswith("ed25519:"):
            return value
        raise ValueError("node_public_key must start with ed25519:")

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, value: str | None) -> str | None:
        if value is None or value.startswith("ed25519:"):
            return value
        raise ValueError("signature must start with ed25519:")

    @field_validator("categories")
    @classmethod
    def validate_categories(cls, values: list[str]) -> list[str]:
        for value in values:
            if not re.fullmatch(CATEGORY_PATTERN, value):
                raise ValueError(
                    "categories must use lowercase canonical tokens matching ^[a-z0-9][a-z0-9-]*$"
                )
        return values


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
    trust_claims: list[TrustClaimType] = Field(default_factory=list)
    trust_claim_issuers: list[HttpUrl] = Field(default_factory=list)


class AnnounceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(default="ok")
    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(min_length=1, pattern=NODE_ID_PATTERN)
    open: bool
    signed_at: str | None = None
    signature: str | None = None

    @field_validator("signature")
    @classmethod
    def validate_signature(cls, value: str | None) -> str | None:
        if value is None or value.startswith("ed25519:"):
            return value
        raise ValueError("signature must start with ed25519:")


class DiscoverResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[NodeView]
    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime


class DirectoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[DirectoryNodeView]
    registry_version: str = Field(default=PROTOCOL_VERSION)
    query_time: datetime
    registry_metadata: RegistryMetadata


class RegistryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tier: int = Field(ge=0)
    url: HttpUrl


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


class RegistryInfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry_version: str = Field(default=PROTOCOL_VERSION)
    registry_url: HttpUrl
    backups: list[RegistryEntry]


class NodeManifestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifest: NodeManifest
    root_rotation: NodeRootRotation | None = None


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


MirrorSyncStatus = Literal["imported", "skipped", "error"]


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


@dataclass
class StoredNode:
    node: Node
    last_seen: datetime
    last_signed_event_at: datetime | None = None


@dataclass
class StoredManifest:
    manifest: NodeManifest
    stored_at: datetime


@dataclass
class StoredMirrorSource:
    snapshot: RegistrySourceResponse
    imported_at: datetime
    verified_signature: bool
    relayed_by_registry_url: str | None = None


class MirrorSyncState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._last_run_at: datetime | None = None
        self._last_successful_run_at: datetime | None = None
        self._last_results: list[RegistrySyncUpstreamResult] = []

    def record(self, results: list[RegistrySyncUpstreamResult]) -> None:
        with self._lock:
            now = utc_now()
            self._last_run_at = now
            self._last_results = results
            if results and all(result.status != "error" for result in results):
                self._last_successful_run_at = now

    def snapshot(self) -> RegistrySyncStatusResponse:
        with self._lock:
            promotion_counts = store.curated_promotion_counts()
            override_counts = store.curated_override_counts()
            return RegistrySyncStatusResponse(
                query_time=utc_now(),
                registry_metadata=REGISTRY_METADATA,
                configured_upstreams=MIRROR_UPSTREAMS,
                trusted_upstreams=MIRROR_TRUSTED_UPSTREAMS,
                mirror_discovery_policy=MIRROR_DISCOVERY_POLICY,
                curated_index_promotion_policy=CURATED_INDEX_PROMOTION_POLICY,
                curated_promotion_records=promotion_counts["records"],
                curated_promoted_sources=promotion_counts["promoted"],
                curated_denied_sources=promotion_counts["denied"],
                curated_override_records=override_counts["records"],
                active_curated_overrides=override_counts["active"],
                sync_interval_seconds=MIRROR_SYNC_INTERVAL_SECONDS,
                mirror_ttl_seconds=MIRROR_SOURCE_TTL_SECONDS,
                last_run_at=self._last_run_at,
                last_successful_run_at=self._last_successful_run_at,
                last_results=list(self._last_results),
            )


class RegistryStore:
    def __init__(self, *, db_path: str) -> None:
        self._nodes: dict[str, StoredNode] = {}
        self._node_manifests: dict[str, StoredManifest] = {}
        self._identity_events: list[NodeIdentityEvent] = []
        self._identity_records: dict[tuple[str, str], NodeIdentityRecord] = {}
        self._mirror_sources: dict[str, StoredMirrorSource] = {}
        self._curated_active_index: dict[str, CuratedActiveIndexEntry] = {}
        self._curated_promotion_records: dict[str, CuratedPromotionRecord] = {}
        self._curated_overrides: dict[str, CuratedOverrideRecord] = {}
        self._directory_claims: dict[str, DirectoryClaimRecord] = {}
        self._trust_claims: dict[str, TrustClaimRecord] = {}
        self._lock = threading.RLock()
        self._db_path = db_path.strip() or ":memory:"
        self._connection: sqlite3.Connection | None = None
        self._storage_backend = "memory" if self._db_path == ":memory:" else "sqlite"
        self._initialize_persistence()

    @property
    def storage_backend(self) -> str:
        return self._storage_backend

    @property
    def persistence_enabled(self) -> bool:
        return self._connection is not None

    def _initialize_persistence(self) -> None:
        if self._db_path == ":memory:":
            return

        db_file = Path(self._db_path).expanduser()
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(db_file, check_same_thread=False)
        self._connection.execute(
            "CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        self._load_persisted_state()

    def _serialize_datetime(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat()

    def _deserialize_datetime(self, value: str | None) -> datetime | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    def _load_persisted_state(self) -> None:
        assert self._connection is not None
        rows = dict(self._connection.execute("SELECT key, value FROM state").fetchall())

        nodes_payload = json.loads(rows.get("nodes", "{}"))
        manifests_payload = json.loads(rows.get("node_manifests", "{}"))
        events_payload = json.loads(rows.get("identity_events", "[]"))
        records_payload = json.loads(rows.get("identity_records", "[]"))
        mirrors_payload = json.loads(rows.get("mirror_sources", "{}"))
        curated_payload = json.loads(rows.get("curated_active_index", "{}"))
        promotion_payload = json.loads(rows.get("curated_promotion_records", "{}"))
        override_payload = json.loads(rows.get("curated_overrides", "{}"))
        directory_claim_payload = json.loads(rows.get("directory_claims", "{}"))
        trust_claim_payload = json.loads(rows.get("trust_claims", "{}"))

        self._nodes = {
            node_id: StoredNode(
                node=Node(**stored["node"]),
                last_seen=self._deserialize_datetime(stored["last_seen"]) or utc_now(),
                last_signed_event_at=self._deserialize_datetime(stored.get("last_signed_event_at")),
            )
            for node_id, stored in nodes_payload.items()
        }
        self._node_manifests = {
            node_id: StoredManifest(
                manifest=NodeManifest(**stored["manifest"]),
                stored_at=self._deserialize_datetime(stored["stored_at"]) or utc_now(),
            )
            for node_id, stored in manifests_payload.items()
        }
        self._identity_events = [NodeIdentityEvent(**item) for item in events_payload]
        self._identity_records = {
            (record.node_id, record.node_public_key): record
            for record in (NodeIdentityRecord(**item) for item in records_payload)
        }
        self._mirror_sources = {
            normalized_registry_url(registry_url): StoredMirrorSource(
                snapshot=RegistrySourceResponse(**stored["snapshot"]),
                imported_at=self._deserialize_datetime(stored["imported_at"]) or utc_now(),
                verified_signature=bool(stored["verified_signature"]),
                relayed_by_registry_url=stored.get("relayed_by_registry_url"),
            )
            for registry_url, stored in mirrors_payload.items()
        }
        self._curated_active_index = {
            node_id: CuratedActiveIndexEntry(**stored)
            for node_id, stored in curated_payload.items()
        }
        self._curated_promotion_records = {
            record_key: CuratedPromotionRecord(**stored)
            for record_key, stored in promotion_payload.items()
        }
        self._curated_overrides = {
            record_key: CuratedOverrideRecord(**stored)
            for record_key, stored in override_payload.items()
        }
        self._directory_claims = {
            node_id: DirectoryClaimRecord(**stored)
            for node_id, stored in directory_claim_payload.items()
        }
        self._trust_claims = {
            claim_key: TrustClaimRecord(**stored)
            for claim_key, stored in trust_claim_payload.items()
        }
        self._refresh_curated_active_index(now=utc_now())

    def _persist_state(self) -> None:
        if self._connection is None:
            return

        payloads = {
            "nodes": {
                node_id: {
                    "node": stored.node.model_dump(mode="json", exclude_none=True),
                    "last_seen": self._serialize_datetime(stored.last_seen),
                    "last_signed_event_at": self._serialize_datetime(stored.last_signed_event_at),
                }
                for node_id, stored in self._nodes.items()
            },
            "node_manifests": {
                node_id: {
                    "manifest": stored.manifest.model_dump(mode="json", exclude_none=True),
                    "stored_at": self._serialize_datetime(stored.stored_at),
                }
                for node_id, stored in self._node_manifests.items()
            },
            "identity_events": [
                event.model_dump(mode="json", exclude_none=True) for event in self._identity_events
            ],
            "identity_records": [
                record.model_dump(mode="json", exclude_none=True)
                for record in self._identity_records.values()
            ],
            "mirror_sources": {
                registry_url: {
                    "snapshot": stored.snapshot.model_dump(mode="json", exclude_none=True),
                    "imported_at": self._serialize_datetime(stored.imported_at),
                    "verified_signature": stored.verified_signature,
                    "relayed_by_registry_url": stored.relayed_by_registry_url,
                }
                for registry_url, stored in self._mirror_sources.items()
            },
            "curated_active_index": {
                node_id: stored.model_dump(mode="json", exclude_none=True)
                for node_id, stored in self._curated_active_index.items()
            },
            "curated_promotion_records": {
                record_key: stored.model_dump(mode="json", exclude_none=True)
                for record_key, stored in self._curated_promotion_records.items()
            },
            "curated_overrides": {
                record_key: stored.model_dump(mode="json", exclude_none=True)
                for record_key, stored in self._curated_overrides.items()
            },
            "directory_claims": {
                node_id: stored.model_dump(mode="json", exclude_none=True)
                for node_id, stored in self._directory_claims.items()
            },
            "trust_claims": {
                claim_key: stored.model_dump(mode="json", exclude_none=True)
                for claim_key, stored in self._trust_claims.items()
            },
        }

        with self._connection:
            self._connection.executemany(
                "INSERT INTO state(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [
                    (key, json.dumps(value, sort_keys=True, separators=(",", ":")))
                    for key, value in payloads.items()
                ],
            )

    def close(self) -> None:
        with self._lock:
            if self._connection is None:
                return
            self._connection.close()
            self._connection = None

    def announce(self, node: Node) -> StoredNode:
        with self._lock:
            now = utc_now()
            existing = self._nodes.get(node.node_id)
            stored = StoredNode(
                node=node,
                last_seen=now,
                last_signed_event_at=(
                    self._deserialize_datetime(node.signed_at)
                    if node.signed_at
                    else (existing.last_signed_event_at if existing else None)
                ),
            )
            self._nodes[node.node_id] = stored
            self._record_signed_identity(node, now)
            self._persist_state()
            return stored

    def get(self, node_id: str) -> StoredNode | None:
        with self._lock:
            return self._nodes.get(node_id)

    def get_manifest(self, node_id: str) -> StoredManifest | None:
        with self._lock:
            return self._node_manifests.get(node_id)

    def store_manifest(self, payload: NodeManifestRequest) -> StoredManifest:
        with self._lock:
            now = utc_now()
            existing = self._node_manifests.get(payload.manifest.node_id)
            stored = StoredManifest(manifest=payload.manifest, stored_at=now)
            self._node_manifests[payload.manifest.node_id] = stored
            self._apply_manifest_status(payload.manifest, previous=(existing.manifest if existing else None))
            self._persist_state()
            return stored

    def heartbeat(self, payload: HeartbeatRequest) -> StoredNode | None:
        with self._lock:
            stored = self._nodes.get(payload.node_id)
            if stored is None:
                return None
            stored.node.open = payload.open
            stored.last_seen = utc_now()
            if payload.signed_at:
                stored.last_signed_event_at = self._deserialize_datetime(payload.signed_at)
            self._persist_state()
            return stored

    def import_source(
        self,
        payload: RegistrySourceResponse,
        *,
        verified_signature: bool,
    ) -> RegistrySourceImportResponse:
        with self._lock:
            now = utc_now()
            self._store_mirror_source(
                payload,
                verified_signature=verified_signature,
                imported_at=now,
                relayed_by_registry_url=None,
                allow_stale_skip=False,
            )
            imported_relayed_sources = 0
            for mirrored_source in payload.mirrored_sources or []:
                if self._store_mirror_source(
                    self._snapshot_to_response(mirrored_source.snapshot),
                    verified_signature=mirrored_source.verified_signature,
                    imported_at=now,
                    relayed_by_registry_url=str(payload.registry_url),
                    allow_stale_skip=True,
                ):
                    imported_relayed_sources += 1
            self._refresh_curated_active_index(now=now)
            self._persist_state()
            return RegistrySourceImportResponse(
                registry_url=payload.registry_url,
                verified_signature=verified_signature,
                imported_at=now,
                imported_nodes=len(payload.nodes),
                imported_manifests=len(payload.manifests),
                imported_relayed_sources=imported_relayed_sources,
                latest_identity_event_id=payload.latest_identity_event_id,
            )

    def _store_mirror_source(
        self,
        payload: RegistrySourceResponse,
        *,
        verified_signature: bool,
        imported_at: datetime,
        relayed_by_registry_url: str | None,
        allow_stale_skip: bool,
    ) -> bool:
        payload = self._snapshot_to_response(payload)
        registry_url = normalized_registry_url(payload.registry_url)
        existing = self._mirror_sources.get(registry_url)
        if existing is not None and payload.exported_at <= existing.snapshot.exported_at:
            if allow_stale_skip:
                return False
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Imported registry source must be newer than the cached snapshot",
            )

        stored = StoredMirrorSource(
            snapshot=payload,
            imported_at=imported_at,
            verified_signature=verified_signature,
            relayed_by_registry_url=relayed_by_registry_url,
        )
        self._mirror_sources[registry_url] = stored
        return True

    def _snapshot_to_response(self, payload: RegistrySourceSnapshot) -> RegistrySourceResponse:
        return RegistrySourceResponse(**payload.model_dump(mode="json", exclude_none=True))

    def _refresh_curated_active_index(self, *, now: datetime) -> None:
        promoted: dict[str, CuratedActiveIndexEntry] = {}
        promotion_records: dict[str, CuratedPromotionRecord] = {}
        for registry_url, stored in self._mirror_sources.items():
            record, visible_nodes = self._evaluate_curated_promotion_record(
                stored,
                now=now,
            )
            promotion_records[
                curated_promotion_record_key(
                    source_registry_url=record.source_registry_url,
                    source_relay_registry_url=record.source_relay_registry_url,
                )
            ] = record
            if record.decision != "promote":
                continue

            for mirrored in visible_nodes:
                candidate = CuratedActiveIndexEntry(
                    node=mirrored.node,
                    last_seen=mirrored.last_seen,
                    source_registry_url=record.source_registry_url,
                    source_relay_registry_url=record.source_relay_registry_url,
                    source_signature_verified=record.source_signature_verified,
                    source_discovery_basis=record.decision_basis,
                    source_snapshot_hash=record.source_snapshot_hash,
                    source_exported_at=record.source_exported_at,
                    source_imported_at=record.source_imported_at,
                    source_last_synced_at=record.source_last_synced_at,
                    source_freshness_state=record.source_freshness_state,
                )
                existing = promoted.get(mirrored.node.node_id)
                if existing is None or self._curated_entry_priority(candidate) > self._curated_entry_priority(existing):
                    promoted[mirrored.node.node_id] = candidate

        self._curated_promotion_records = promotion_records
        self._curated_active_index = promoted

    def _curated_entry_priority(self, entry: CuratedActiveIndexEntry) -> tuple[int, datetime, datetime]:
        discovery_rank = {
            "manual_override_allow": 3,
            "trusted_upstream": 2,
            "trusted_relayed_upstream": 1,
        }.get(entry.source_discovery_basis, 0)
        return (
            discovery_rank,
            entry.source_exported_at,
            entry.source_imported_at,
        )

    def _curated_entry_is_current(self, entry: CuratedActiveIndexEntry, *, now: datetime) -> bool:
        record = self._curated_promotion_records.get(
            curated_promotion_record_key(
                source_registry_url=entry.source_registry_url,
                source_relay_registry_url=entry.source_relay_registry_url,
            )
        )
        if record is None or record.decision != "promote":
            return False
        if not record.active or not record.promotion_eligible:
            return False
        if record.decision_basis != entry.source_discovery_basis:
            return False
        if record.source_snapshot_hash != entry.source_snapshot_hash:
            return False
        if entry.node.node_id not in record.promoted_node_ids:
            return False
        return True

    def _visible_mirror_nodes(self, stored: StoredMirrorSource) -> list[RegistrySourceNode]:
        manifests_by_node_id = {
            item.manifest.node_id: item.manifest for item in stored.snapshot.manifests
        }
        visible_nodes: list[RegistrySourceNode] = []
        for mirrored in stored.snapshot.nodes:
            if not mirrored.node.open:
                continue
            if not self._mirror_node_is_manifest_visible(
                mirrored.node,
                manifests_by_node_id=manifests_by_node_id,
            ):
                continue
            visible_nodes.append(mirrored)
        return visible_nodes

    def _evaluate_curated_promotion_record(
        self,
        stored: StoredMirrorSource,
        *,
        now: datetime,
    ) -> tuple[CuratedPromotionRecord, list[RegistrySourceNode]]:
        active = stored.imported_at >= now - timedelta(seconds=MIRROR_SOURCE_TTL_SECONDS)
        source_registry_url = stored.snapshot.registry_url
        source_relay_registry_url = stored.relayed_by_registry_url
        source_snapshot_hash = registry_source_hash(stored.snapshot)
        visible_nodes = self._visible_mirror_nodes(stored) if active else []
        promoted_node_ids = [item.node.node_id for item in visible_nodes]
        freshness_state: FreshnessState = "fresh" if active else "stale"

        automatic_decision: CuratedPromotionDecision = "deny"
        automatic_decision_basis = "manual_only_policy"
        automatic_decision_reason = "Imported evidence stays raw-only under manual_only promotion policy"
        promotion_eligible = False
        hard_safety_blocked = False

        if not active:
            automatic_decision_basis = "expired"
            automatic_decision_reason = "Mirror source expired from the curated promotion window"
            hard_safety_blocked = True
        elif not stored.verified_signature:
            automatic_decision_basis = "unverified_source"
            automatic_decision_reason = "Curated promotion requires a verified upstream source signature"
            hard_safety_blocked = True
        elif not visible_nodes:
            automatic_decision_basis = "no_visible_nodes"
            automatic_decision_reason = "Mirror source currently has no manifest-valid visible nodes to promote"
            hard_safety_blocked = True
        elif not REGISTRY_METADATA.capabilities.can_curate_active_index:
            automatic_decision_basis = "curation_disabled"
            automatic_decision_reason = "This registry is not allowed to curate a discoverable active index"
        elif CURATED_INDEX_PROMOTION_POLICY == "manual_only":
            automatic_decision_basis = "manual_only_policy"
            automatic_decision_reason = "Imported evidence stays raw-only under manual_only promotion policy"
        else:
            source_url = normalized_registry_url(source_registry_url)
            relay_url = (
                normalized_registry_url(source_relay_registry_url)
                if source_relay_registry_url
                else None
            )
            trust_urls_configured = bool(TRUSTED_MIRROR_UPSTREAM_URLS)
            if relay_url:
                if trust_urls_configured and relay_url not in TRUSTED_MIRROR_UPSTREAM_URLS:
                    automatic_decision_basis = "untrusted_relay"
                    automatic_decision_reason = "Relayed mirror source is not in the trusted upstream set"
                else:
                    automatic_decision = "promote"
                    automatic_decision_basis = "trusted_relayed_upstream"
                    automatic_decision_reason = "Verified relayed upstream is allowed by current curated promotion policy"
                    promotion_eligible = True
            elif trust_urls_configured and source_url not in TRUSTED_MIRROR_UPSTREAM_URLS:
                automatic_decision_basis = "untrusted_upstream"
                automatic_decision_reason = "Upstream registry is not in the trusted upstream set"
            else:
                automatic_decision = "promote"
                automatic_decision_basis = "trusted_upstream"
                automatic_decision_reason = "Verified trusted upstream is allowed by current curated promotion policy"
                promotion_eligible = True

        override = self._active_curated_override(
            source_registry_url=source_registry_url,
            source_relay_registry_url=source_relay_registry_url,
            now=now,
        )

        decision = automatic_decision
        decision_origin: CuratedPromotionDecisionOrigin = "automatic"
        decision_basis = automatic_decision_basis
        decision_reason = automatic_decision_reason

        if override is not None and not hard_safety_blocked and REGISTRY_METADATA.capabilities.can_curate_active_index:
            if override.decision == "deny":
                decision = "deny"
                decision_origin = "manual"
                decision_basis = "manual_override_deny"
                decision_reason = override.reason
                promotion_eligible = False
            else:
                decision = "promote"
                decision_origin = "manual"
                decision_basis = "manual_override_allow"
                decision_reason = override.reason
                promotion_eligible = True

        if decision != "promote":
            promoted_node_ids = []

        return (
            CuratedPromotionRecord(
                source_registry_url=source_registry_url,
                source_relay_registry_url=source_relay_registry_url,
                source_signature_verified=stored.verified_signature,
                source_snapshot_hash=source_snapshot_hash,
                source_exported_at=stored.snapshot.exported_at,
                source_imported_at=stored.imported_at,
                source_last_synced_at=stored.imported_at,
                source_freshness_state=freshness_state,
                automatic_decision=automatic_decision,
                automatic_decision_basis=automatic_decision_basis,
                automatic_decision_reason=automatic_decision_reason,
                override_decision=(override.decision if override else None),
                override_reason=(override.reason if override else None),
                override_set_by=(override.set_by if override else None),
                override_expires_at=(override.expires_at if override else None),
                override_set_at=(override.set_at if override else None),
                decision=decision,
                decision_origin=decision_origin,
                decision_basis=decision_basis,
                decision_reason=decision_reason,
                active=active,
                promotion_eligible=promotion_eligible,
                promoted_node_ids=promoted_node_ids,
                decided_at=now,
                last_evaluated_at=now,
            ),
            visible_nodes,
        )

    def _active_curated_override(
        self,
        *,
        source_registry_url: str | HttpUrl,
        source_relay_registry_url: str | HttpUrl | None,
        now: datetime,
    ) -> CuratedOverrideRecord | None:
        record = self._curated_overrides.get(
            curated_promotion_record_key(
                source_registry_url=source_registry_url,
                source_relay_registry_url=source_relay_registry_url,
            )
        )
        if record is None:
            return None
        if record.expires_at is not None and record.expires_at <= now:
            return None
        return record

    def _mirror_source_promotion_status(
        self,
        stored: StoredMirrorSource,
        *,
        now: datetime,
    ) -> tuple[bool, bool, str]:
        active = stored.imported_at >= now - timedelta(seconds=MIRROR_SOURCE_TTL_SECONDS)
        if not active:
            return False, False, "expired"
        if not stored.verified_signature:
            return True, False, "unverified_source"
        source_registry_url = normalized_registry_url(stored.snapshot.registry_url)
        relay_registry_url = (
            normalized_registry_url(stored.relayed_by_registry_url)
            if stored.relayed_by_registry_url
            else None
        )
        trust_urls_configured = bool(TRUSTED_MIRROR_UPSTREAM_URLS)
        if relay_registry_url:
            if trust_urls_configured and relay_registry_url not in TRUSTED_MIRROR_UPSTREAM_URLS:
                return True, False, "untrusted_relay"
            return True, True, "trusted_relayed_upstream"
        if trust_urls_configured and source_registry_url not in TRUSTED_MIRROR_UPSTREAM_URLS:
            return True, False, "untrusted_upstream"
        return True, True, "trusted_upstream"

    def mirror_status(self) -> RegistryMirrorStatusResponse:
        with self._lock:
            now = utc_now()
            sources = []
            for _, stored in sorted(self._mirror_sources.items(), key=lambda item: item[0]):
                active, discovery_eligible, discovery_basis = self._mirror_source_discovery_status(
                    stored,
                    now=now,
                )
                sources.append(
                    RegistryMirrorStatus(
                        registry_url=stored.snapshot.registry_url,
                        imported_at=stored.imported_at,
                        expires_at=stored.imported_at + timedelta(seconds=MIRROR_SOURCE_TTL_SECONDS),
                        active=active,
                        discovery_eligible=discovery_eligible,
                        discovery_basis=discovery_basis,
                        verified_signature=stored.verified_signature,
                        relayed_by_registry_url=stored.relayed_by_registry_url,
                        imported_nodes=len(stored.snapshot.nodes),
                        imported_manifests=len(stored.snapshot.manifests),
                        latest_identity_event_id=stored.snapshot.latest_identity_event_id,
                    )
                )
            return RegistryMirrorStatusResponse(
                query_time=utc_now(),
                sources=sources,
            )

    def curated_promotion_counts(self) -> dict[str, int]:
        with self._lock:
            records = len(self._curated_promotion_records)
            promoted = sum(1 for record in self._curated_promotion_records.values() if record.decision == "promote")
            denied = records - promoted
            return {
                "records": records,
                "promoted": promoted,
                "denied": denied,
            }

    def curated_override_counts(self) -> dict[str, int]:
        with self._lock:
            now = utc_now()
            records = len(self._curated_overrides)
            active = sum(
                1
                for record in self._curated_overrides.values()
                if record.expires_at is None or record.expires_at > now
            )
            return {
                "records": records,
                "active": active,
            }

    def curated_promotion_status(self) -> CuratedPromotionStatusResponse:
        with self._lock:
            now = utc_now()
            self._refresh_curated_active_index(now=now)
            records = sorted(
                self._curated_promotion_records.values(),
                key=lambda record: (
                    normalized_registry_url(record.source_registry_url),
                    normalized_registry_url(record.source_relay_registry_url)
                    if record.source_relay_registry_url
                    else "",
                ),
            )
            return CuratedPromotionStatusResponse(
                query_time=now,
                registry_metadata=REGISTRY_METADATA,
                curated_index_promotion_policy=CURATED_INDEX_PROMOTION_POLICY,
                records=records,
            )

    def curated_override_status(self) -> CuratedOverrideStatusResponse:
        with self._lock:
            now = utc_now()
            records = sorted(
                self._curated_overrides.values(),
                key=lambda record: (
                    normalized_registry_url(record.source_registry_url),
                    normalized_registry_url(record.source_relay_registry_url)
                    if record.source_relay_registry_url
                    else "",
                ),
            )
            return CuratedOverrideStatusResponse(
                query_time=now,
                registry_metadata=REGISTRY_METADATA,
                records=records,
            )

    def set_curated_override(self, payload: CuratedOverrideRequest) -> CuratedOverrideRecord:
        with self._lock:
            now = utc_now()
            if payload.expires_at is not None and payload.expires_at <= now:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="expires_at must be in the future when setting a curated override",
                )
            record = CuratedOverrideRecord(
                source_registry_url=payload.source_registry_url,
                source_relay_registry_url=payload.source_relay_registry_url,
                decision=payload.decision,
                reason=payload.reason,
                set_by=payload.set_by,
                expires_at=payload.expires_at,
                set_at=now,
            )
            self._curated_overrides[
                curated_promotion_record_key(
                    source_registry_url=record.source_registry_url,
                    source_relay_registry_url=record.source_relay_registry_url,
                )
            ] = record
            self._refresh_curated_active_index(now=now)
            self._persist_state()
            return record

    def _active_directory_claim(self, node_id: str, *, now: datetime) -> DirectoryClaimRecord | None:
        record = self._directory_claims.get(node_id)
        if record is None:
            return None
        if record.expires_at is not None and record.expires_at <= now:
            return None
        return record

    def _directory_claim_is_visible(self, record: DirectoryClaimRecord) -> bool:
        claims = set(record.claims)
        if "hidden" in claims or "spam" in claims:
            return False
        if "local_only" in claims and REGISTRY_METADATA.registry_type != "local":
            return False
        return True

    def _active_trust_claims(self, node_id: str, *, now: datetime) -> list[TrustClaimRecord]:
        active: list[TrustClaimRecord] = []
        for record in self._trust_claims.values():
            if record.node_id != node_id:
                continue
            if record.expires_at is not None and record.expires_at <= now:
                continue
            active.append(record)
        active.sort(
            key=lambda record: (
                normalized_registry_url(record.issuer_registry_url),
                record.issued_at,
            )
        )
        return active

    def _node_known_for_trust_claim(self, node_id: str, *, now: datetime) -> bool:
        self._refresh_curated_active_index(now=now)
        if node_id in self._nodes or node_id in self._curated_active_index:
            return True
        return any(record.node_id == node_id for record in self._identity_records.values())

    def _build_directory_node_view(
        self,
        *,
        node: NodeView,
        claim: DirectoryClaimRecord | None,
        trust_claim_records: list[TrustClaimRecord],
    ) -> DirectoryNodeView:
        trust_claims: list[TrustClaimType] = []
        seen_claims: set[TrustClaimType] = set()
        trust_claim_issuers: list[str] = []
        seen_issuers: set[str] = set()
        for record in trust_claim_records:
            issuer = normalized_registry_url(record.issuer_registry_url)
            if issuer not in seen_issuers:
                trust_claim_issuers.append(issuer)
                seen_issuers.add(issuer)
            for claim_name in record.claims:
                if claim_name in seen_claims:
                    continue
                trust_claims.append(claim_name)
                seen_claims.add(claim_name)
        return DirectoryNodeView(
            **node.model_dump(mode="json"),
            directory_claims=(list(claim.claims) if claim else []),
            directory_reason=(claim.reason if claim else None),
            directory_set_by=(claim.set_by if claim else None),
            directory_expires_at=(claim.expires_at if claim else None),
            directory_set_at=(claim.set_at if claim else None),
            trust_claims=trust_claims,
            trust_claim_issuers=trust_claim_issuers,
        )

    def directory_claim_counts(self) -> dict[str, int]:
        with self._lock:
            now = utc_now()
            records = len(self._directory_claims)
            active = sum(
                1
                for record in self._directory_claims.values()
                if record.expires_at is None or record.expires_at > now
            )
            return {
                "records": records,
                "active": active,
            }

    def directory_claim_status(self) -> DirectoryClaimStatusResponse:
        with self._lock:
            records = sorted(
                self._directory_claims.values(),
                key=lambda record: record.node_id,
            )
            return DirectoryClaimStatusResponse(
                query_time=utc_now(),
                registry_metadata=REGISTRY_METADATA,
                records=records,
            )

    def trust_claim_counts(self) -> dict[str, int]:
        with self._lock:
            now = utc_now()
            records = len(self._trust_claims)
            active = sum(
                1
                for record in self._trust_claims.values()
                if record.expires_at is None or record.expires_at > now
            )
            return {
                "records": records,
                "active": active,
            }

    def trust_claim_status(self) -> TrustClaimStatusResponse:
        with self._lock:
            records = sorted(
                self._trust_claims.values(),
                key=lambda record: (
                    normalized_registry_url(record.issuer_registry_url),
                    record.node_id,
                ),
            )
            return TrustClaimStatusResponse(
                query_time=utc_now(),
                registry_metadata=REGISTRY_METADATA,
                records=records,
            )

    def set_directory_claim(self, payload: DirectoryClaimRequest) -> DirectoryClaimRecord:
        with self._lock:
            now = utc_now()
            if payload.expires_at is not None and payload.expires_at <= now:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="expires_at must be in the future when setting a directory claim",
                )
            record = DirectoryClaimRecord(
                node_id=payload.node_id,
                claims=payload.claims,
                reason=payload.reason,
                set_by=payload.set_by,
                expires_at=payload.expires_at,
                set_at=now,
            )
            self._directory_claims[payload.node_id] = record
            self._persist_state()
            return record

    def issue_trust_claim(
        self,
        payload: TrustClaimIssueRequest,
        *,
        issuer_registry_url: str,
        issuer_registry_public_key: str,
        issuer_private_key: str,
    ) -> TrustClaimRecord:
        with self._lock:
            now = utc_now()
            if payload.expires_at is not None and payload.expires_at <= now:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="expires_at must be in the future when issuing a trust claim",
                )
            if not self._node_known_for_trust_claim(payload.node_id, now=now):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Cannot issue a trust claim for an unknown node_id",
                )

            unsigned = TrustClaimRecord(
                issuer_registry_url=normalized_registry_url(issuer_registry_url),
                issuer_registry_public_key=issuer_registry_public_key,
                node_id=payload.node_id,
                claims=list(payload.claims),
                reason=payload.reason,
                issued_at=now,
                expires_at=payload.expires_at,
                signature="ed25519:pending",
            )
            claim_payload = trust_claim_payload(unsigned)
            signature = sign_payload(claim_payload, issuer_private_key)
            record = TrustClaimRecord(
                **{
                    **claim_payload,
                    "signature": signature,
                }
            )
            self._trust_claims[
                trust_claim_record_key(
                    issuer_registry_url=record.issuer_registry_url,
                    node_id=record.node_id,
                )
            ] = record
            self._persist_state()
            return record

    def import_trust_claim(self, claim: TrustClaimRecord) -> TrustClaimImportResponse:
        with self._lock:
            require_valid_trust_claim(claim)
            now = utc_now()
            record_key = trust_claim_record_key(
                issuer_registry_url=claim.issuer_registry_url,
                node_id=claim.node_id,
            )
            existing = self._trust_claims.get(record_key)
            if existing is not None:
                if claim.issued_at < existing.issued_at:
                    return TrustClaimImportResponse(
                        issuer_registry_url=claim.issuer_registry_url,
                        node_id=claim.node_id,
                        imported_at=now,
                    )
                if claim.issued_at == existing.issued_at and claim.signature != existing.signature:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Imported trust claim conflicts with the cached claim at the same issued_at",
                    )

            self._trust_claims[record_key] = claim
            self._persist_state()
            return TrustClaimImportResponse(
                issuer_registry_url=claim.issuer_registry_url,
                node_id=claim.node_id,
                imported_at=now,
            )

    def discover(
        self,
        *,
        lat: float,
        lng: float,
        radius: float,
        category: str | None,
        country: str | None,
    ) -> list[NodeView]:
        with self._lock:
            now = utc_now()
            self._refresh_curated_active_index(now=now)
            cutoff = now - timedelta(seconds=HEARTBEAT_TTL_SECONDS)
            results_by_node_id: dict[str, NodeView] = {}

            for stored in self._nodes.values():
                view = self._build_discover_view(
                    node=stored.node,
                    last_seen=stored.last_seen,
                    manifests_by_node_id=None,
                    source_kind="local",
                    source_registry_url=None,
                    source_relay_registry_url=None,
                    source_signature_verified=None,
                    source_discovery_basis="local_registry",
                    source_snapshot_hash=None,
                    source_exported_at=None,
                    source_imported_at=None,
                    source_last_synced_at=None,
                    source_freshness_state=None,
                    lat=lat,
                    lng=lng,
                    radius=radius,
                    category=category,
                    country=country,
                    cutoff=cutoff,
                )
                if view is None:
                    continue
                results_by_node_id[stored.node.node_id] = view

            for entry in self._curated_active_index.values():
                if entry.node.node_id in results_by_node_id:
                    continue
                if not self._curated_entry_is_current(entry, now=now):
                    continue
                view = self._build_discover_view(
                    node=entry.node,
                    last_seen=entry.last_seen,
                    manifests_by_node_id={},
                    source_kind=entry.source_kind,
                    source_registry_url=str(entry.source_registry_url),
                    source_relay_registry_url=entry.source_relay_registry_url,
                    source_signature_verified=entry.source_signature_verified,
                    source_discovery_basis=entry.source_discovery_basis,
                    source_snapshot_hash=entry.source_snapshot_hash,
                    source_exported_at=entry.source_exported_at,
                    source_imported_at=entry.source_imported_at,
                    source_last_synced_at=entry.source_last_synced_at,
                    source_freshness_state=entry.source_freshness_state,
                    lat=lat,
                    lng=lng,
                    radius=radius,
                    category=category,
                    country=country,
                    cutoff=cutoff,
                )
                if view is None:
                    continue
                results_by_node_id[entry.node.node_id] = view

            return sorted(
                results_by_node_id.values(),
                key=lambda node: ((node.distance_km or 0), node.name.lower()),
            )

    def directory(
        self,
        *,
        lat: float,
        lng: float,
        radius: float,
        category: str | None,
        country: str | None,
    ) -> list[DirectoryNodeView]:
        with self._lock:
            now = utc_now()
            nodes = self.discover(
                lat=lat,
                lng=lng,
                radius=radius,
                category=category,
                country=country,
            )
            visible: list[DirectoryNodeView] = []
            for node in nodes:
                claim = self._active_directory_claim(node.node_id, now=now)
                if claim is not None and not self._directory_claim_is_visible(claim):
                    continue
                trust_claim_records = (
                    self._active_trust_claims(node.node_id, now=now)
                    if REGISTRY_METADATA.capabilities.can_moderate_directory
                    else []
                )
                visible.append(
                    self._build_directory_node_view(
                        node=node,
                        claim=claim,
                        trust_claim_records=trust_claim_records,
                    )
                )
            return visible

    def identity_log(self) -> IdentityLogResponse:
        with self._lock:
            records = sorted(
                self._identity_records.values(),
                key=lambda record: (record.node_id, record.node_public_key),
            )
            return IdentityLogResponse(
                query_time=utc_now(),
                records=records,
                events=list(self._identity_events),
            )

    def export_source(self, *, registry_url: str) -> RegistrySourceResponse:
        with self._lock:
            now = utc_now()
            nodes = [
                RegistrySourceNode(
                    node=stored.node,
                    last_seen=stored.last_seen,
                    last_signed_event_at=stored.last_signed_event_at,
                )
                for _, stored in sorted(self._nodes.items(), key=lambda item: item[0])
            ]
            manifests = [
                RegistrySourceManifest(
                    manifest=stored.manifest,
                    stored_at=stored.stored_at,
                )
                for _, stored in sorted(self._node_manifests.items(), key=lambda item: item[0])
            ]
            records = sorted(
                self._identity_records.values(),
                key=lambda record: (record.node_id, record.node_public_key),
            )
            events = list(self._identity_events)
            mirrored_sources: list[RegistrySourceMirrorExport] = []
            if REGISTRY_SOURCE_REEXPORT_POLICY == "local_plus_trusted_mirrors":
                for stored, discovery_basis in self._discoverable_mirror_sources(now=now).values():
                    if discovery_basis != "trusted_upstream" or not stored.verified_signature:
                        continue
                    mirrored_sources.append(
                        RegistrySourceMirrorExport(
                            snapshot=self._response_to_snapshot(stored.snapshot),
                            imported_at=stored.imported_at,
                            verified_signature=stored.verified_signature,
                            discovery_eligible=True,
                            discovery_basis=discovery_basis,
                            relayed_by_registry_url=registry_url,
                        )
                    )
            return RegistrySourceResponse(
                registry_url=registry_url,
                registry_metadata=REGISTRY_METADATA,
                export_scope=REGISTRY_SOURCE_REEXPORT_POLICY,
                exported_at=now,
                storage_backend=self.storage_backend,
                latest_identity_event_id=(events[-1].event_id if events else None),
                nodes=nodes,
                manifests=manifests,
                identity_records=records,
                identity_events=events,
                mirrored_sources=(mirrored_sources or None),
            )

    def _response_to_snapshot(self, payload: RegistrySourceResponse) -> RegistrySourceSnapshot:
        return RegistrySourceSnapshot(
            **payload.model_dump(mode="json", exclude={"mirrored_sources"}, exclude_none=True)
        )

    def _active_mirror_sources(self, *, now: datetime) -> dict[str, StoredMirrorSource]:
        cutoff = now - timedelta(seconds=MIRROR_SOURCE_TTL_SECONDS)
        return {
            registry_url: stored
            for registry_url, stored in self._mirror_sources.items()
            if stored.imported_at >= cutoff
        }

    def _discoverable_mirror_sources(
        self,
        *,
        now: datetime,
    ) -> dict[str, tuple[StoredMirrorSource, str]]:
        discoverable: dict[str, tuple[StoredMirrorSource, str]] = {}
        for registry_url, stored in self._mirror_sources.items():
            _, discovery_eligible, discovery_basis = self._mirror_source_discovery_status(
                stored,
                now=now,
            )
            if discovery_eligible:
                discoverable[registry_url] = (stored, discovery_basis)
        return discoverable

    def _mirror_source_discovery_status(
        self,
        stored: StoredMirrorSource,
        *,
        now: datetime,
    ) -> tuple[bool, bool, str]:
        active = stored.imported_at >= now - timedelta(seconds=MIRROR_SOURCE_TTL_SECONDS)
        if not active:
            return False, False, "expired"

        if MIRROR_DISCOVERY_POLICY == "all_active":
            return True, True, "all_active_policy"

        registry_url = normalized_registry_url(stored.snapshot.registry_url)
        if registry_url in TRUSTED_MIRROR_UPSTREAM_URLS:
            return True, True, "trusted_upstream"
        if stored.relayed_by_registry_url:
            relayed_by_registry_url = normalized_registry_url(stored.relayed_by_registry_url)
            if relayed_by_registry_url in TRUSTED_MIRROR_UPSTREAM_URLS and stored.verified_signature:
                return True, True, "trusted_relayed_upstream"
        return True, False, "not_trusted"

    def _build_discover_view(
        self,
        *,
        node: Node,
        last_seen: datetime,
        manifests_by_node_id: dict[str, NodeManifest] | None,
        source_kind: DiscoverySourceKind,
        source_registry_url: str | None,
        source_relay_registry_url: str | None,
        source_signature_verified: bool | None,
        source_discovery_basis: str | None,
        source_snapshot_hash: str | None,
        source_exported_at: datetime | None,
        source_imported_at: datetime | None,
        source_last_synced_at: datetime | None,
        source_freshness_state: FreshnessState | None,
        lat: float,
        lng: float,
        radius: float,
        category: str | None,
        country: str | None,
        cutoff: datetime,
    ) -> NodeView | None:
        if not node.open or last_seen < cutoff:
            return None
        if manifests_by_node_id is None:
            if not self._node_is_manifest_visible(node):
                return None
        else:
            if not self._mirror_node_is_manifest_visible(node, manifests_by_node_id=manifests_by_node_id):
                return None
        if country and node.country != country:
            return None
        if category and category not in node.categories:
            return None

        distance_km = haversine_km(lat, lng, node.location.lat, node.location.lng)
        if distance_km > radius:
            return None

        return NodeView(
            **node.model_dump(),
            last_seen=last_seen,
            distance_km=round(distance_km, 3),
            source_kind=source_kind,
            source_registry_url=source_registry_url,
            source_relay_registry_url=source_relay_registry_url,
            source_signature_verified=source_signature_verified,
            source_discovery_basis=source_discovery_basis,
            source_snapshot_hash=source_snapshot_hash,
            source_exported_at=source_exported_at,
            source_imported_at=source_imported_at,
            source_last_synced_at=source_last_synced_at,
            source_freshness_state=source_freshness_state,
        )

    def _record_signed_identity(self, node: Node, recorded_at: datetime) -> None:
        if not node.node_public_key or not node.signed_at or not node.signature:
            return

        scope = identity_scope(node.endpoint)
        record_key = (node.node_id, node.node_public_key)
        record = self._identity_records.get(record_key)
        if record is None:
            record = NodeIdentityRecord(
                node_id=node.node_id,
                node_public_key=node.node_public_key,
                first_seen=recorded_at,
                last_seen=recorded_at,
                status="active",
                scope=scope,
                event_count=1,
            )
            self._identity_records[record_key] = record
        else:
            record.last_seen = recorded_at
            record.scope = scope
            record.event_count += 1

        self._identity_events.append(
            NodeIdentityEvent(
                event_id=len(self._identity_events) + 1,
                node_id=node.node_id,
                node_public_key=node.node_public_key,
                signed_at=node.signed_at,
                announcement_signature=node.signature,
                announcement_hash=announcement_hash(node),
                status=record.status,
                scope=scope,
                recorded_at=recorded_at,
            )
        )

    def _apply_manifest_status(
        self,
        manifest: NodeManifest,
        *,
        previous: NodeManifest | None,
    ) -> None:
        current_keys = {entry.node_public_key: entry for entry in manifest.keys}

        if previous is not None:
            previous_keys = {entry.node_public_key: entry for entry in previous.keys}
            for node_public_key in previous_keys:
                record = self._identity_records.get((manifest.node_id, node_public_key))
                if record is None or node_public_key in current_keys:
                    continue
                record.status = "rotated" if previous.root_public_key != manifest.root_public_key else "revoked"

        for entry in manifest.keys:
            record = self._identity_records.get((manifest.node_id, entry.node_public_key))
            if record is None:
                continue
            record.status = "active" if entry.status == "active" else "revoked"

    def _node_is_manifest_visible(self, node: Node) -> bool:
        if not node.node_public_key:
            return True
        stored_manifest = self._node_manifests.get(node.node_id)
        if stored_manifest is None:
            return True
        entry = manifest_key_for_node(manifest=stored_manifest.manifest, node=node)
        if entry is None:
            return False
        return manifest_key_is_currently_active(entry)

    def _mirror_node_is_manifest_visible(
        self,
        node: Node,
        *,
        manifests_by_node_id: dict[str, NodeManifest],
    ) -> bool:
        if not node.node_public_key:
            return True
        manifest = manifests_by_node_id.get(node.node_id)
        if manifest is None:
            return True
        entry = manifest_key_for_node(manifest=manifest, node=node)
        if entry is None:
            return False
        return manifest_key_is_currently_active(entry)

def load_registry_private_key() -> str | None:
    inline_private_key = os.environ.get("P4P_REGISTRY_PRIVATE_KEY", "").strip()
    if inline_private_key:
        return inline_private_key

    key_file = os.environ.get("P4P_REGISTRY_KEY_FILE", "").strip()
    if not key_file:
        return None
    return load_or_create_private_key(Path(key_file).expanduser())


def load_registry_metadata() -> RegistryMetadata:
    raw = os.environ.get("P4P_REGISTRY_METADATA", "").strip()
    if raw:
        return RegistryMetadata(**json.loads(raw))
    return RegistryMetadata()


REGISTRY_URL = os.environ.get("P4P_REGISTRY_URL", "").strip()
BACKUP_REGISTRIES = load_backup_registries()
MIRROR_UPSTREAMS = load_mirror_upstreams()
EXPLICIT_MIRROR_TRUSTED_UPSTREAMS = load_mirror_trusted_upstreams()
MIRROR_SYNC_INTERVAL_SECONDS = max(0, int(os.environ.get("P4P_MIRROR_SYNC_INTERVAL_SECONDS", "60")))
MIRROR_SOURCE_TTL_SECONDS = max(1, int(os.environ.get("P4P_MIRROR_SOURCE_TTL_SECONDS", "600")))
REGISTRY_PRIVATE_KEY = load_registry_private_key()
REGISTRY_PUBLIC_KEY = (
    public_key_from_private(REGISTRY_PRIVATE_KEY) if REGISTRY_PRIVATE_KEY else None
)
REGISTRY_METADATA = load_registry_metadata()


def normalized_registry_url(value: str | HttpUrl) -> str:
    return str(value).rstrip("/")


def curated_promotion_record_key(
    *,
    source_registry_url: str | HttpUrl,
    source_relay_registry_url: str | HttpUrl | None,
) -> str:
    source = normalized_registry_url(source_registry_url)
    relay = normalized_registry_url(source_relay_registry_url) if source_relay_registry_url else ""
    return f"{source}||{relay}"


def trust_claim_record_key(
    *,
    issuer_registry_url: str | HttpUrl,
    node_id: str,
) -> str:
    return f"{normalized_registry_url(issuer_registry_url)}||{node_id}"


MIRROR_TRUSTED_UPSTREAMS = resolve_trusted_mirror_upstreams(
    configured_upstreams=MIRROR_UPSTREAMS,
    explicit_trusted_upstreams=EXPLICIT_MIRROR_TRUSTED_UPSTREAMS,
)
TRUSTED_MIRROR_UPSTREAM_URLS = {
    normalized_registry_url(upstream.url) for upstream in MIRROR_TRUSTED_UPSTREAMS
}
MIRROR_DISCOVERY_POLICY = resolve_mirror_discovery_policy(
    configured_upstreams=MIRROR_UPSTREAMS,
    trusted_upstreams=MIRROR_TRUSTED_UPSTREAMS,
)
REGISTRY_SOURCE_REEXPORT_POLICY = resolve_registry_source_reexport_policy()
CURATED_INDEX_PROMOTION_POLICY = resolve_curated_index_promotion_policy()
MIRROR_SYNC_STATE = MirrorSyncState()
REGISTRY_DB_PATH = os.environ.get("P4P_REGISTRY_DB_PATH", ":memory:").strip() or ":memory:"
store = RegistryStore(db_path=REGISTRY_DB_PATH)


async def sync_registry_source_from_upstream(
    upstream: MirrorUpstream,
    client: httpx.AsyncClient,
) -> RegistrySyncUpstreamResult:
    upstream_url = normalized_registry_url(upstream.url)
    self_url = normalized_registry_url(REGISTRY_URL) if REGISTRY_URL else None
    if self_url and upstream_url == self_url:
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="skipped",
            detail="Skipped self mirror source",
        )

    try:
        response = await client.get(f"{upstream_url}/registry-source")
        response.raise_for_status()
        snapshot = RegistrySourceResponse(**response.json())
        verified_signature = require_valid_registry_source(snapshot)
        imported = store.import_source(snapshot, verified_signature=verified_signature)
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="imported",
            verified_signature=imported.verified_signature,
            imported_nodes=imported.imported_nodes,
            imported_manifests=imported.imported_manifests,
            latest_identity_event_id=imported.latest_identity_event_id,
        )
    except HTTPException as exc:
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="error",
            detail=str(exc.detail),
        )
    except httpx.HTTPError as exc:
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="error",
            detail=str(exc),
        )
    except Exception as exc:
        return RegistrySyncUpstreamResult(
            registry_url=upstream.url,
            status="error",
            detail=str(exc),
        )


async def run_mirror_sync_once() -> RegistrySyncResponse:
    require_registry_capability(
        REGISTRY_METADATA.capabilities.can_relay_sources,
        detail="This registry is not allowed to relay upstream sources",
    )
    started_at = utc_now()
    results: list[RegistrySyncUpstreamResult] = []

    if MIRROR_UPSTREAMS:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for upstream in MIRROR_UPSTREAMS:
                results.append(await sync_registry_source_from_upstream(upstream, client))

    response = RegistrySyncResponse(
        run_started_at=started_at,
        run_completed_at=utc_now(),
        upstreams=results,
    )
    MIRROR_SYNC_STATE.record(results)
    return response


@asynccontextmanager
async def app_lifespan(_: FastAPI):
    task: asyncio.Task[None] | None = None
    stop_event: asyncio.Event | None = None

    if (
        MIRROR_UPSTREAMS
        and MIRROR_SYNC_INTERVAL_SECONDS > 0
        and REGISTRY_METADATA.capabilities.can_relay_sources
    ):
        stop_event = asyncio.Event()

        async def sync_loop() -> None:
            while True:
                await run_mirror_sync_once()
                try:
                    assert stop_event is not None
                    await asyncio.wait_for(stop_event.wait(), timeout=MIRROR_SYNC_INTERVAL_SECONDS)
                    return
                except asyncio.TimeoutError:
                    continue

        task = asyncio.create_task(sync_loop())

    try:
        yield
    finally:
        if stop_event is not None:
            stop_event.set()
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

app = FastAPI(
    title="P4P Registry",
    version=PROTOCOL_VERSION,
    summary="Reference registry for the P4P v0.1 protocol.",
    lifespan=app_lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def has_node_signature_fields(node: Node) -> bool:
    return bool(node.node_public_key or node.signed_at or node.signature)


def node_payload(node: Node) -> dict[str, Any]:
    return node.model_dump(mode="json", exclude_none=True)


def announcement_hash(node: Node) -> str:
    raw = json.dumps(node_payload(node), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def registry_source_hash(payload: RegistrySourceSnapshot | RegistrySourceResponse) -> str:
    raw = json.dumps(
        payload.model_dump(mode="json", exclude={"mirrored_sources"}, exclude_none=True),
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


def require_registry_capability(enabled: bool, *, detail: str) -> None:
    if enabled:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )


def require_registry_signing_key() -> tuple[str, str]:
    if not REGISTRY_PRIVATE_KEY or not REGISTRY_PUBLIC_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="This registry cannot issue signed trust claims without a registry signing key",
        )
    return REGISTRY_PRIVATE_KEY, REGISTRY_PUBLIC_KEY


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
            detail=(
                f"{field_name} must be newer than the last accepted signed event for this node_id"
            ),
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

    if payload.mirrored_sources and payload.export_scope != "local_plus_trusted_mirrors":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mirrored source re-export requires export_scope=local_plus_trusted_mirrors",
        )

    for mirrored_source in payload.mirrored_sources or []:
        if not mirrored_source.verified_signature:
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
        require_valid_registry_source_snapshot(mirrored_source.snapshot)

    return verified_signature


def require_allowed_announcement_update(node: Node, existing: StoredNode | None) -> None:
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


@app.get("/health")
def health() -> dict[str, Any]:
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
        "configured_mirror_upstreams": len(MIRROR_UPSTREAMS),
        "trusted_mirror_upstreams": len(MIRROR_TRUSTED_UPSTREAMS),
        "mirror_discovery_policy": MIRROR_DISCOVERY_POLICY,
        "curated_index_promotion_policy": CURATED_INDEX_PROMOTION_POLICY,
        "registry_source_reexport_policy": REGISTRY_SOURCE_REEXPORT_POLICY,
        "registry_metadata": REGISTRY_METADATA.model_dump(mode="json", exclude_none=True),
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
        "mirror_sync_interval_seconds": MIRROR_SYNC_INTERVAL_SECONDS,
        "mirror_ttl_seconds": MIRROR_SOURCE_TTL_SECONDS,
        "storage_backend": store.storage_backend,
        "persistence_enabled": store.persistence_enabled,
        "registry_signing_enabled": bool(REGISTRY_PRIVATE_KEY),
    }


@app.post("/announce", response_model=AnnounceResponse)
def announce(node: Node) -> AnnounceResponse:
    require_registry_capability(
        REGISTRY_METADATA.capabilities.can_onboard_nodes,
        detail="This registry is not allowed to onboard nodes",
    )
    if node.protocol_version != PROTOCOL_VERSION:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported protocol_version: {node.protocol_version}",
        )
    existing = store.get(node.node_id)
    require_allowed_announcement_update(node, existing)
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
    return DirectoryResponse(nodes=nodes, query_time=utc_now(), registry_metadata=REGISTRY_METADATA)


@app.get("/identity-log", response_model=IdentityLogResponse)
def identity_log() -> IdentityLogResponse:
    return store.identity_log()


@app.get("/registry-source", response_model=RegistrySourceResponse)
def registry_source(request: Request) -> RegistrySourceResponse:
    if REGISTRY_SOURCE_REEXPORT_POLICY != "local_only":
        require_registry_capability(
            REGISTRY_METADATA.capabilities.can_reexport_sources,
            detail="This registry is not allowed to re-export sources",
        )
    registry_url = REGISTRY_URL or str(request.base_url).rstrip("/")
    snapshot = store.export_source(registry_url=registry_url)
    payload = snapshot.model_dump(mode="json", exclude_none=True)
    payload["registry_public_key"] = REGISTRY_PUBLIC_KEY
    if REGISTRY_PRIVATE_KEY:
        payload["signature"] = sign_payload(payload, REGISTRY_PRIVATE_KEY)
    return RegistrySourceResponse(**payload)


@app.post("/registry-source/import", response_model=RegistrySourceImportResponse)
def registry_source_import(payload: RegistrySourceResponse) -> RegistrySourceImportResponse:
    require_registry_capability(
        REGISTRY_METADATA.capabilities.can_relay_sources,
        detail="This registry is not allowed to relay upstream sources",
    )
    verified_signature = require_valid_registry_source(payload)
    return store.import_source(payload, verified_signature=verified_signature)


@app.get("/registry-mirrors", response_model=RegistryMirrorStatusResponse)
def registry_mirrors() -> RegistryMirrorStatusResponse:
    return store.mirror_status()


@app.get("/curated-promotions", response_model=CuratedPromotionStatusResponse)
def curated_promotions() -> CuratedPromotionStatusResponse:
    return store.curated_promotion_status()


@app.get("/curated-overrides", response_model=CuratedOverrideStatusResponse)
def curated_overrides() -> CuratedOverrideStatusResponse:
    return store.curated_override_status()


@app.post("/curated-overrides", response_model=CuratedOverrideResponse)
def curated_override(payload: CuratedOverrideRequest) -> CuratedOverrideResponse:
    require_registry_capability(
        REGISTRY_METADATA.capabilities.can_curate_active_index,
        detail="This registry is not allowed to curate a discoverable active index",
    )
    return CuratedOverrideResponse(override=store.set_curated_override(payload))


@app.get("/directory-claims", response_model=DirectoryClaimStatusResponse)
def directory_claims() -> DirectoryClaimStatusResponse:
    return store.directory_claim_status()


@app.post("/directory-claims", response_model=DirectoryClaimResponse)
def directory_claim(payload: DirectoryClaimRequest) -> DirectoryClaimResponse:
    require_registry_capability(
        REGISTRY_METADATA.capabilities.can_moderate_directory,
        detail="This registry is not allowed to moderate a public directory",
    )
    return DirectoryClaimResponse(record=store.set_directory_claim(payload))


@app.get("/trust-claims", response_model=TrustClaimStatusResponse)
def trust_claims() -> TrustClaimStatusResponse:
    return store.trust_claim_status()


@app.post("/trust-claims", response_model=TrustClaimResponse)
def trust_claim_issue(payload: TrustClaimIssueRequest, request: Request) -> TrustClaimResponse:
    require_registry_capability(
        REGISTRY_METADATA.capabilities.can_issue_trust_claims,
        detail="This registry is not allowed to issue signed trust claims",
    )
    registry_private_key, registry_public_key = require_registry_signing_key()
    issuer_registry_url = REGISTRY_URL or str(request.base_url).rstrip("/")
    return TrustClaimResponse(
        claim=store.issue_trust_claim(
            payload,
            issuer_registry_url=issuer_registry_url,
            issuer_registry_public_key=registry_public_key,
            issuer_private_key=registry_private_key,
        )
    )


@app.post("/trust-claims/import", response_model=TrustClaimImportResponse)
def trust_claim_import(payload: TrustClaimRecord) -> TrustClaimImportResponse:
    require_registry_capability(
        REGISTRY_METADATA.capabilities.can_moderate_directory,
        detail="This registry is not allowed to project trust claims into a moderated directory",
    )
    local_payload = TrustClaimRecord(**payload.model_dump(mode="json", exclude_none=True))
    return store.import_trust_claim(local_payload)


@app.post("/registry-sync", response_model=RegistrySyncResponse)
async def registry_sync() -> RegistrySyncResponse:
    return await run_mirror_sync_once()


@app.get("/registry-sync", response_model=RegistrySyncStatusResponse)
def registry_sync_status() -> RegistrySyncStatusResponse:
    return MIRROR_SYNC_STATE.snapshot()


@app.get("/registry-info", response_model=RegistryInfoResponse)
def registry_info(request: Request) -> RegistryInfoResponse:
    registry_url = REGISTRY_URL or str(request.base_url).rstrip("/")
    backups = BACKUP_REGISTRIES or [RegistryEntry(tier=0, url=registry_url)]
    return RegistryInfoResponse(
        registry_url=registry_url,
        backups=backups,
    )
