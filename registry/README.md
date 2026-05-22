# registry

Canonical `v0.1` registry implementation.

Responsibilities:
- accept `POST /announce`
- accept `POST /node-manifest`
- accept `POST /heartbeat`
- verify signed announcements and signed heartbeats when a node uses Ed25519 identity
- verify optional root-signed node delegation when a node uses a delegated operational key
- verify optional root-signed node manifests and previous-root rotation proofs
- record public identity-log events for signed announcements
- serve `GET /discover`
- serve `GET /directory`
- serve `GET /identity-log`
- serve `GET /registry-source`
- accept `POST /registry-source/import`
- serve `GET /registry-mirrors`
- serve `GET /curated-promotions`
- serve `GET /curated-overrides`
- accept `POST /curated-overrides`
- serve `GET /directory-claims`
- accept `POST /directory-claims`
- serve `GET /trust-claims`
- accept `POST /trust-claims`
- accept `POST /trust-claims/import`
- serve `POST /registry-sync`
- serve `GET /registry-sync`
- serve `GET /registry-info`
- track `last_seen`
- hide nodes whose heartbeat is older than 180 seconds

Target:
FastAPI with default in-memory storage and optional SQLite-backed snapshot persistence.

Administrative write routes use `P4P_REGISTRY_ADMIN_TOKEN` and accept either:

- `Authorization: Bearer <token>`
- `X-P4P-Registry-Token: <token>`

This token is required for:

- `GET /registry-mirrors`
- `GET /curated-promotions`
- `GET /curated-overrides`
- `GET /directory-claims`
- `GET /trust-claims`
- `GET /registry-sync`
- `POST /registry-source/import`
- `POST /curated-overrides`
- `POST /directory-claims`
- `POST /trust-claims`
- `POST /trust-claims/import`
- `POST /registry-sync`

## Files

- `main.py` — FastAPI app and registry store
- `requirements.txt` — minimal runtime dependencies

## Local run

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
P4P_REGISTRY_URL=http://127.0.0.1:8000 \
P4P_BACKUP_REGISTRIES='[{"tier":0,"url":"http://127.0.0.1:8000"},{"tier":1,"url":"http://127.0.0.1:8002"}]' \
P4P_REGISTRY_DB_PATH=/tmp/p4p-registry.sqlite3 \
P4P_MIRROR_UPSTREAMS=http://127.0.0.1:8002 \
P4P_MIRROR_TRUSTED_UPSTREAMS=http://127.0.0.1:8002 \
P4P_MIRROR_DISCOVERY_POLICY=trusted_only \
P4P_REGISTRY_SOURCE_REEXPORT_POLICY=local_plus_trusted_mirrors \
P4P_REGISTRY_ADMIN_TOKEN=change-this \
P4P_MIRROR_SYNC_INTERVAL_SECONDS=60 \
P4P_MIRROR_SOURCE_TTL_SECONDS=600 \
./.venv/bin/uvicorn main:app --reload --port 8000
```

Then open:

- `GET /health`
- `POST /announce`
- `POST /node-manifest`
- `POST /heartbeat`
- `GET /discover`
- `GET /directory`
- `GET /identity-log`
- `GET /registry-source`
- `POST /registry-source/import`
- `GET /registry-mirrors` (admin token)
- `GET /curated-promotions` (admin token)
- `GET /curated-overrides` (admin token)
- `POST /curated-overrides`
- `GET /directory-claims` (admin token)
- `POST /directory-claims`
- `GET /trust-claims` (admin token)
- `POST /trust-claims`
- `POST /trust-claims/import`
- `POST /registry-sync`
- `GET /registry-sync` (admin token)
- `GET /registry-info`

## Notes

- Storage defaults to in-memory for `v0.1`
- Set `P4P_REGISTRY_DB_PATH` to a writable SQLite file path when you want restart persistence
- `last_seen` TTL is 180 seconds
- signed node ids are protected from unsigned, tampered, or older signed metadata updates once a newer signed event has been accepted
- delegated node ids may also carry a root-signed authorization for an operational node key
- root-managed node ids may also carry a separate root-signed manifest so revoked keys disappear from discovery and heartbeat acceptance
- root key changes for an existing root-managed node id require a previous-root rotation proof
- `/identity-log` is read-only and contains public signing metadata, not node private keys
- `/registry-source` is a full registry snapshot surface for later mirroring or umbrella ingestion
- set `P4P_REGISTRY_KEY_FILE` or `P4P_REGISTRY_PRIVATE_KEY` when the snapshot should carry a registry signature
- signed registry-source export requires a canonical `P4P_REGISTRY_URL`; a signing-enabled registry will not fall back to request host headers when producing a signed snapshot
- unsigned registry-source export may still fall back to request base when `P4P_REGISTRY_URL` is absent, but only for loopback-local request bases; public-looking host fallback is rejected
- `POST /registry-source/import` requires the registry admin token and still rejects unsigned public source snapshots; unsigned loopback sources are only accepted when the importing registry is itself running as a local loopback reference environment
- that same self-import guard also applies in loopback-dev without a canonical `P4P_REGISTRY_URL`: a local reference registry still cannot import its own unsigned snapshot back into mirror cache just because the payload URL came from request-base fallback
- even in that loopback-dev exception, unsigned mirrored sources stay raw-only: a trusted upstream URL without a verified source signature does not become `trusted_upstream` in mirror status, health counts, or provenance ranking
- `POST /registry-source/import` also rejects a registry's own signed snapshot, and relayed trusted snapshots skip nested copies of the importing registry itself, so admin import cannot accidentally create a self-mirror alongside the local source of truth
- mirrored nodes become discoverable, but local node state still wins on `node_id` collisions
- discover results now carry provenance fields so clients can distinguish `local` vs `mirrored` nodes and see whether a mirrored result is visible via `trusted_upstream` or the looser `all_active_policy`
- mirrored discovery may also report `trusted_relayed_upstream` when the original upstream snapshot arrived through a trusted umbrella or country relay
- `P4P_MIRROR_UPSTREAMS` configures which upstream registries are polled for `GET /registry-source`
- `P4P_MIRROR_TRUSTED_UPSTREAMS` can pin which mirrored sources are allowed into ordinary discovery
- if `P4P_MIRROR_DISCOVERY_POLICY` is unset, the runtime defaults to `trusted_only` when upstream config exists and falls back to `all_active` only when no trust list or upstream set exists
- `P4P_CURATED_INDEX_PROMOTION_POLICY` decides whether trusted mirrored evidence stays raw-only (`manual_only`) or may be promoted into the curated active index (`trusted_mirrors`)
- `P4P_REGISTRY_METADATA` declares runtime scope and capability metadata such as `local`, `country`, `vertical`, or `umbrella`
- `P4P_REGISTRY_SOURCE_REEXPORT_POLICY=local_plus_trusted_mirrors` allows the registry to attach trusted mirrored upstream snapshots to `GET /registry-source` without flattening them into the top-level local source
- imported relay snapshots that claim `export_scope=local_plus_trusted_mirrors` are only accepted when the signed top-level registry metadata also declares `can_reexport_sources`, so downstream import cannot be tricked by a capability-inconsistent re-export payload
- relay payloads that carry nested mirrored sources must themselves verify as signed snapshots; an unsigned loopback relay cannot piggyback signed upstream evidence through the re-export lane
- re-exported mirrored sources must also verify as signed snapshots themselves; a relay cannot mark an unsigned nested loopback payload as `verified_signature=true` and smuggle it through a signed top-level export
- re-exported mirrored sources must also be unique by nested `registry_url`; a relay envelope cannot carry two competing nested snapshots for the same upstream source and leave downstream import order-dependent
- re-exported mirrored sources must also stay external to the relay itself; a relay envelope cannot nest a second snapshot of its own `registry_url` and rely on downstream import to silently skip it
- downstream import now preserves each nested mirrored source's own `imported_at` when evaluating freshness, so a relay cannot silently reset a stale upstream source into a fresh downstream mirror just by re-exporting it later
- a cached source that arrived through a relay stays classified as relayed in mirror status and provenance; trusting the original source URL does not retroactively turn a relayed path into `trusted_upstream`
- `POST /registry-sync` requires the registry admin token and triggers one fetch/import cycle for configured upstream registries
- `GET /registry-sync` requires the registry admin token and exposes last run state for the sync runtime
- `GET /registry-mirrors` requires the registry admin token and shows whether each cached mirror source is still active, whether it is currently discovery-eligible, and whether it was relayed by another registry
- `GET /curated-promotions` requires the registry admin token and shows the persisted promotion decision record for each mirrored source, including whether it was promoted or denied and which node ids currently flow into the curated active index
- `GET /curated-overrides` requires the registry admin token and shows persisted manual allow/deny overrides for mirrored sources
- `POST /curated-overrides` requires the registry admin token plus `can_curate_active_index` and may steer discoverability only among still-valid mirrored evidence
- `GET /directory` is a separate moderated public directory layered on top of `GET /discover`
- `GET /directory-claims` requires the registry admin token and shows persisted directory-level claims such as `reviewed`, `verified`, `hidden`, `spam`, or `local_only`
- `POST /directory-claims` requires the registry admin token plus `can_moderate_directory` and may annotate or hide discoverable nodes without rewriting source truth
- `GET /trust-claims` requires the registry admin token and shows signed trust claims currently stored by the registry
- `POST /trust-claims` requires the registry admin token, `can_issue_trust_claims`, and a configured registry signing key
- signed trust-claim issuance also requires a canonical `P4P_REGISTRY_URL`, so the issuer URL comes from registry config rather than request-host fallback
- `POST /trust-claims/import` requires the registry admin token plus `can_moderate_directory` and only imports signed trust claims for moderated-directory projection
- `can_curate_active_index`, `can_moderate_directory`, and `can_issue_trust_claims` are intentionally separate powers in the runtime metadata
- mirrored source cache expires from discovery after `P4P_MIRROR_SOURCE_TTL_SECONDS`
- imported mirror records always land in raw mirror cache first
- `GET /discover` only reads local canonical nodes plus the curated active index
- curated promotion records persist the decision path between raw mirrored evidence and the curated active index
- curated overrides sit above automatic promotion records but cannot revive stale, revoked, or invalid upstream evidence
- moderated directory claims sit above `GET /discover` and do not change raw evidence, curated promotion, or curated override history
- signed trust claims sit above the moderated directory as transportable positive annotations and do not change node identity or `GET /discover`
- stale or revoked upstream evidence is de-promoted out of the curated active index during sync/import and guarded again at read time
- `GET /registry-source` still treats local registry state as canonical top-level source; trusted mirrored state is only re-exported as nested upstream snapshots
- `/health` exposes storage mode plus mirrored-source counts, curated active index counts, curated promotion counts, curated override counts, directory claim counts, trust-claim counts, and registry metadata
- unsigned legacy nodes remain accepted during early `v0.1` development
- if `P4P_BACKUP_REGISTRIES` is omitted, `/registry-info` falls back to the current registry only
- `/registry-info` is advisory in `v0.1`; clients should merge it with pinned local seeds rather than treating it as authoritative
- this is the reference registry, not a central order platform
