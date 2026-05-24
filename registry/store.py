from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException, status

from p4p_core import HeartbeatRequest, NodeManifest, NodeManifestRequest, resolve_enabled_modules, utc_now

from registry.config import RegistryConfig, normalized_registry_url
from registry.models import (
    CuratedActiveIndexEntry,
    CuratedOverrideRecord,
    CuratedOverrideRequest,
    CuratedOverrideStatusResponse,
    CuratedPromotionDecision,
    CuratedPromotionDecisionOrigin,
    CuratedPromotionRecord,
    CuratedPromotionStatusResponse,
    DirectoryClaimRecord,
    DirectoryClaimRequest,
    DirectoryClaimStatusResponse,
    DirectoryNodeView,
    FreshnessState,
    IdentityLogResponse,
    Node,
    NodeIdentityEvent,
    NodeIdentityRecord,
    NodeView,
    RegistryMirrorStatus,
    RegistryMirrorStatusResponse,
    RegistrySourceImportResponse,
    RegistrySourceManifest,
    RegistrySourceMirrorExport,
    RegistrySourceNode,
    RegistrySourceResponse,
    RegistrySourceSnapshot,
    RegistrySyncStatusResponse,
    RegistrySyncUpstreamResult,
    TrustClaimImportResponse,
    TrustClaimIssueRequest,
    TrustClaimRecord,
    TrustClaimStatusResponse,
    TrustClaimType,
    haversine_km,
)
from p4p_core.constants import HEARTBEAT_TTL_SECONDS
from p4p_identity import sign_payload


def curated_promotion_record_key(
    *,
    source_registry_url: str,
    source_relay_registry_url: str | None,
) -> str:
    source = normalized_registry_url(source_registry_url)
    relay = normalized_registry_url(source_relay_registry_url) if source_relay_registry_url else ""
    return f"{source}||{relay}"


def trust_claim_record_key(
    *,
    issuer_registry_url: str,
    node_id: str,
) -> str:
    return f"{normalized_registry_url(issuer_registry_url)}||{node_id}"


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


@dataclass(frozen=True)
class MirrorSourceStoreDecision:
    stored: bool
    detail: str | None = None


@dataclass(frozen=True)
class SourceImportOutcome:
    response: RegistrySourceImportResponse
    stored_top_level: bool
    detail: str | None = None


class MirrorSyncState:
    def __init__(self, *, config: RegistryConfig, store: "RegistryStore") -> None:
        self._config = config
        self._store = store
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
            promotion_counts = self._store.curated_promotion_counts()
            override_counts = self._store.curated_override_counts()
            return RegistrySyncStatusResponse(
                query_time=utc_now(),
                registry_metadata=self._config.registry_metadata,
                configured_upstreams=self._config.mirror_upstreams,
                trusted_upstreams=self._config.mirror_trusted_upstreams,
                mirror_discovery_policy=self._config.mirror_discovery_policy,
                curated_index_promotion_policy=self._config.curated_index_promotion_policy,
                curated_promotion_records=promotion_counts["records"],
                curated_promoted_sources=promotion_counts["promoted"],
                curated_denied_sources=promotion_counts["denied"],
                curated_override_records=override_counts["records"],
                active_curated_overrides=override_counts["active"],
                sync_interval_seconds=self._config.mirror_sync_interval_seconds,
                mirror_ttl_seconds=self._config.mirror_source_ttl_seconds,
                last_run_at=self._last_run_at,
                last_successful_run_at=self._last_successful_run_at,
                last_results=list(self._last_results),
            )


class RegistryStore:
    def __init__(self, *, db_path: str, config: RegistryConfig) -> None:
        self._config = config
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
        allow_stale_skip: bool = False,
    ) -> RegistrySourceImportResponse:
        return self.import_source_with_outcome(
            payload,
            verified_signature=verified_signature,
            allow_stale_skip=allow_stale_skip,
        ).response

    def import_source_with_outcome(
        self,
        payload: RegistrySourceResponse,
        *,
        verified_signature: bool,
        allow_stale_skip: bool = False,
    ) -> SourceImportOutcome:
        with self._lock:
            now = utc_now()
            top_level_decision = self._store_mirror_source(
                payload,
                verified_signature=verified_signature,
                imported_at=now,
                relayed_by_registry_url=None,
                allow_stale_skip=allow_stale_skip,
            )
            if not top_level_decision.stored:
                return SourceImportOutcome(
                    response=RegistrySourceImportResponse(
                        registry_url=payload.registry_url,
                        verified_signature=verified_signature,
                        imported_at=now,
                        imported_nodes=0,
                        imported_manifests=0,
                        imported_relayed_sources=0,
                        latest_identity_event_id=payload.latest_identity_event_id,
                    ),
                    stored_top_level=False,
                    detail=top_level_decision.detail,
                )
            imported_relayed_sources = 0
            for mirrored_source in payload.mirrored_sources or []:
                decision = self._store_mirror_source(
                    self._snapshot_to_response(mirrored_source.snapshot),
                    verified_signature=mirrored_source.verified_signature,
                    imported_at=mirrored_source.imported_at,
                    relayed_by_registry_url=str(payload.registry_url),
                    allow_stale_skip=True,
                )
                if decision.stored:
                    imported_relayed_sources += 1
            self._refresh_curated_active_index(now=now)
            self._persist_state()
            return SourceImportOutcome(
                response=RegistrySourceImportResponse(
                    registry_url=payload.registry_url,
                    verified_signature=verified_signature,
                    imported_at=now,
                    imported_nodes=len(payload.nodes),
                    imported_manifests=len(payload.manifests),
                    imported_relayed_sources=imported_relayed_sources,
                    latest_identity_event_id=payload.latest_identity_event_id,
                ),
                stored_top_level=True,
            )

    def _store_mirror_source(
        self,
        payload: RegistrySourceResponse,
        *,
        verified_signature: bool,
        imported_at: datetime,
        relayed_by_registry_url: str | None,
        allow_stale_skip: bool,
    ) -> MirrorSourceStoreDecision:
        payload = self._snapshot_to_response(payload)
        registry_url = normalized_registry_url(payload.registry_url)
        self_registry_url = (
            normalized_registry_url(self._config.registry_url)
            if self._config.registry_url
            else None
        )
        from registry.validation import registry_source_content_hash

        if self_registry_url and registry_url == self_registry_url:
            if relayed_by_registry_url is not None or allow_stale_skip:
                return MirrorSourceStoreDecision(
                    stored=False,
                    detail="Skipped self mirror source",
                )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Registry cannot import its own source snapshot",
            )
        existing = self._mirror_sources.get(registry_url)
        if existing is not None:
            incoming_content_hash = registry_source_content_hash(payload)
            existing_content_hash = registry_source_content_hash(existing.snapshot)
            incoming_provenance_priority = self._mirror_source_provenance_priority(
                registry_url=payload.registry_url,
                verified_signature=verified_signature,
                relayed_by_registry_url=relayed_by_registry_url,
            )
            existing_provenance_priority = self._mirror_source_provenance_priority(
                registry_url=existing.snapshot.registry_url,
                verified_signature=existing.verified_signature,
                relayed_by_registry_url=existing.relayed_by_registry_url,
            )
            incoming_priority = (
                payload.exported_at,
                *incoming_provenance_priority,
            )
            existing_priority = (
                existing.snapshot.exported_at,
                *existing_provenance_priority,
            )
            if incoming_content_hash == existing_content_hash:
                if incoming_provenance_priority < existing_provenance_priority:
                    if allow_stale_skip:
                        return MirrorSourceStoreDecision(
                            stored=False,
                            detail="Skipped weaker mirror snapshot",
                        )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Imported registry source must be newer than the cached snapshot",
                    )
                if incoming_provenance_priority == existing_provenance_priority:
                    if allow_stale_skip:
                        return MirrorSourceStoreDecision(
                            stored=False,
                            detail="Skipped unchanged mirror snapshot",
                        )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Imported registry source must be newer than the cached snapshot",
                    )
            elif incoming_priority < existing_priority:
                if allow_stale_skip:
                    if payload.exported_at < existing.snapshot.exported_at:
                        detail = "Skipped older mirror snapshot"
                    else:
                        detail = "Skipped weaker mirror snapshot"
                    return MirrorSourceStoreDecision(stored=False, detail=detail)
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Imported registry source must be newer than the cached snapshot",
                )
            elif incoming_priority == existing_priority:
                if allow_stale_skip:
                    return MirrorSourceStoreDecision(
                        stored=False,
                        detail="Skipped weaker mirror snapshot",
                    )
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
        return MirrorSourceStoreDecision(stored=True)

    def _mirror_source_provenance_priority(
        self,
        *,
        registry_url: str,
        verified_signature: bool,
        relayed_by_registry_url: str | None,
    ) -> tuple[int, int, int]:
        source_url = normalized_registry_url(registry_url)
        relay_url = (
            normalized_registry_url(relayed_by_registry_url)
            if relayed_by_registry_url
            else None
        )
        discovery_rank = 0
        if self._config.mirror_discovery_policy == "all_active":
            discovery_rank = 1
        if relay_url is not None:
            if relay_url in self._config.trusted_mirror_upstream_urls and verified_signature:
                discovery_rank = max(discovery_rank, 2)
        elif source_url in self._config.trusted_mirror_upstream_urls and verified_signature:
            discovery_rank = max(discovery_rank, 3)
        return (
            discovery_rank,
            1 if verified_signature else 0,
            1 if relayed_by_registry_url is None else 0,
        )

    def _snapshot_to_response(self, payload: RegistrySourceSnapshot) -> RegistrySourceResponse:
        return RegistrySourceResponse(**payload.model_dump(mode="json", exclude_none=True))

    def _refresh_curated_active_index(self, *, now: datetime) -> None:
        promoted: dict[str, CuratedActiveIndexEntry] = {}
        promotion_records: dict[str, CuratedPromotionRecord] = {}
        for registry_url, stored in self._mirror_sources.items():
            record, visible_nodes = self._evaluate_curated_promotion_record(stored, now=now)
            promotion_records[
                curated_promotion_record_key(
                    source_registry_url=str(record.source_registry_url),
                    source_relay_registry_url=(
                        str(record.source_relay_registry_url)
                        if record.source_relay_registry_url
                        else None
                    ),
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
        return (discovery_rank, entry.source_exported_at, entry.source_imported_at)

    def _curated_entry_is_current(self, entry: CuratedActiveIndexEntry, *, now: datetime) -> bool:
        record = self._curated_promotion_records.get(
            curated_promotion_record_key(
                source_registry_url=str(entry.source_registry_url),
                source_relay_registry_url=(
                    str(entry.source_relay_registry_url) if entry.source_relay_registry_url else None
                ),
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
        from registry.validation import registry_source_hash

        active = stored.imported_at >= now - timedelta(seconds=self._config.mirror_source_ttl_seconds)
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
        elif not self._config.registry_metadata.capabilities.can_curate_active_index:
            automatic_decision_basis = "curation_disabled"
            automatic_decision_reason = "This registry is not allowed to curate a discoverable active index"
        elif self._config.curated_index_promotion_policy == "manual_only":
            automatic_decision_basis = "manual_only_policy"
            automatic_decision_reason = "Imported evidence stays raw-only under manual_only promotion policy"
        else:
            source_url = normalized_registry_url(source_registry_url)
            relay_url = normalized_registry_url(source_relay_registry_url) if source_relay_registry_url else None
            trust_urls_configured = bool(self._config.trusted_mirror_upstream_urls)
            if relay_url:
                if trust_urls_configured and relay_url not in self._config.trusted_mirror_upstream_urls:
                    automatic_decision_basis = "untrusted_relay"
                    automatic_decision_reason = "Relayed mirror source is not in the trusted upstream set"
                else:
                    automatic_decision = "promote"
                    automatic_decision_basis = "trusted_relayed_upstream"
                    automatic_decision_reason = "Verified relayed upstream is allowed by current curated promotion policy"
                    promotion_eligible = True
            elif trust_urls_configured and source_url not in self._config.trusted_mirror_upstream_urls:
                automatic_decision_basis = "untrusted_upstream"
                automatic_decision_reason = "Upstream registry is not in the trusted upstream set"
            else:
                automatic_decision = "promote"
                automatic_decision_basis = "trusted_upstream"
                automatic_decision_reason = "Verified trusted upstream is allowed by current curated promotion policy"
                promotion_eligible = True

        override = self._active_curated_override(
            source_registry_url=str(source_registry_url),
            source_relay_registry_url=source_relay_registry_url,
            now=now,
        )

        decision = automatic_decision
        decision_origin: CuratedPromotionDecisionOrigin = "automatic"
        decision_basis = automatic_decision_basis
        decision_reason = automatic_decision_reason

        if override is not None and not hard_safety_blocked and self._config.registry_metadata.capabilities.can_curate_active_index:
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
        source_registry_url: str,
        source_relay_registry_url: str | None,
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
                        expires_at=stored.imported_at + timedelta(seconds=self._config.mirror_source_ttl_seconds),
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
            return RegistryMirrorStatusResponse(query_time=utc_now(), sources=sources)

    def curated_promotion_counts(self) -> dict[str, int]:
        with self._lock:
            records = len(self._curated_promotion_records)
            promoted = sum(1 for record in self._curated_promotion_records.values() if record.decision == "promote")
            denied = records - promoted
            return {"records": records, "promoted": promoted, "denied": denied}

    def curated_override_counts(self) -> dict[str, int]:
        with self._lock:
            now = utc_now()
            records = len(self._curated_overrides)
            active = sum(
                1
                for record in self._curated_overrides.values()
                if record.expires_at is None or record.expires_at > now
            )
            return {"records": records, "active": active}

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
                registry_metadata=self._config.registry_metadata,
                curated_index_promotion_policy=self._config.curated_index_promotion_policy,
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
                registry_metadata=self._config.registry_metadata,
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
                    source_registry_url=str(record.source_registry_url),
                    source_relay_registry_url=(
                        str(record.source_relay_registry_url)
                        if record.source_relay_registry_url
                        else None
                    ),
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
        if "local_only" in claims and self._config.registry_metadata.registry_type != "local":
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
        resolved_modules = resolve_enabled_modules(node.modules, strict=False)
        declared_module_ids = set(resolved_modules.module_ids)
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
            module_declarations=resolved_modules.declarations(),
            undeclared_modules=[module_id for module_id in node.modules if module_id not in declared_module_ids],
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
            return {"records": records, "active": active}

    def directory_claim_status(self) -> DirectoryClaimStatusResponse:
        with self._lock:
            records = sorted(self._directory_claims.values(), key=lambda record: record.node_id)
            return DirectoryClaimStatusResponse(
                query_time=utc_now(),
                registry_metadata=self._config.registry_metadata,
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
            return {"records": records, "active": active}

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
                registry_metadata=self._config.registry_metadata,
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
        from registry.validation import trust_claim_payload

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
            record = TrustClaimRecord(**{**claim_payload, "signature": signature})
            self._trust_claims[
                trust_claim_record_key(
                    issuer_registry_url=str(record.issuer_registry_url),
                    node_id=record.node_id,
                )
            ] = record
            self._persist_state()
            return record

    def import_trust_claim(self, claim: TrustClaimRecord) -> TrustClaimImportResponse:
        from registry.validation import require_valid_trust_claim

        with self._lock:
            require_valid_trust_claim(claim)
            now = utc_now()
            record_key = trust_claim_record_key(
                issuer_registry_url=str(claim.issuer_registry_url),
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
                    source_relay_registry_url=(
                        str(entry.source_relay_registry_url) if entry.source_relay_registry_url else None
                    ),
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
                    if self._config.registry_metadata.capabilities.can_moderate_directory
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
                if self._node_is_manifest_visible(stored.node)
            ]
            manifests = [
                RegistrySourceManifest(manifest=stored.manifest, stored_at=stored.stored_at)
                for _, stored in sorted(self._node_manifests.items(), key=lambda item: item[0])
            ]
            records = sorted(
                self._identity_records.values(),
                key=lambda record: (record.node_id, record.node_public_key),
            )
            events = list(self._identity_events)
            mirrored_sources: list[RegistrySourceMirrorExport] = []
            if self._config.registry_source_reexport_policy == "local_plus_trusted_mirrors":
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
                registry_metadata=self._config.registry_metadata,
                export_scope=self._config.registry_source_reexport_policy,
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
        cutoff = now - timedelta(seconds=self._config.mirror_source_ttl_seconds)
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
        active = stored.imported_at >= now - timedelta(seconds=self._config.mirror_source_ttl_seconds)
        if not active:
            return False, False, "expired"

        if self._config.mirror_discovery_policy == "all_active":
            return True, True, "all_active_policy"

        registry_url = normalized_registry_url(stored.snapshot.registry_url)
        if stored.relayed_by_registry_url:
            relayed_by_registry_url = normalized_registry_url(stored.relayed_by_registry_url)
            if (
                relayed_by_registry_url in self._config.trusted_mirror_upstream_urls
                and stored.verified_signature
            ):
                return True, True, "trusted_relayed_upstream"
            return True, False, "not_trusted"
        if registry_url in self._config.trusted_mirror_upstream_urls and stored.verified_signature:
            return True, True, "trusted_upstream"
        return True, False, "not_trusted"

    def _build_discover_view(
        self,
        *,
        node: Node,
        last_seen: datetime,
        manifests_by_node_id: dict[str, NodeManifest] | None,
        source_kind: str,
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
        from registry.validation import announcement_hash, identity_scope

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
        from registry.validation import manifest_key_for_node, manifest_key_is_currently_active

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
        from registry.validation import manifest_key_for_node, manifest_key_is_currently_active

        if not node.node_public_key:
            return True
        manifest = manifests_by_node_id.get(node.node_id)
        if manifest is None:
            return True
        entry = manifest_key_for_node(manifest=manifest, node=node)
        if entry is None:
            return False
        return manifest_key_is_currently_active(entry)


__all__ = [
    "MirrorSyncState",
    "RegistryStore",
    "StoredManifest",
    "StoredMirrorSource",
    "StoredNode",
    "curated_promotion_record_key",
    "trust_claim_record_key",
]
