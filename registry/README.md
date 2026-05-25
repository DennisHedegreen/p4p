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
- top-level source lists (`nodes`, `manifests`, `identity_records`) and re-exported `mirrored_sources` are treated as canonical sets keyed by their natural identity fields, not as order-sensitive lists; pure reorderings do not create fake upstream changes
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
- a mirrored source only counts as having visible/promotable nodes when those nodes are also fresh enough for ordinary discovery; mirror-status and curated promotion now use the same heartbeat freshness boundary as `discover()`
- a mirrored source only counts as `discovery_eligible` when it is fresh/trusted under the current policy and still has at least one manifest-valid visible node; trusted raw source snapshots with `no_visible_nodes` stay cached for proof and downstream sync, but do not count as discoverable
- `GET /registry-source` still treats local registry state as canonical top-level source; trusted mirrored state is only re-exported as nested upstream snapshots
- `GET /registry-source` does not export signed top-level nodes before they have a current manifest; unsigned local proof metadata may still exist, but manifest-less signed nodes do not get presented as canonical top-level source truth
- a registry-source snapshot must not repeat the same `node_id` in its top-level `nodes` list; downstream import rejects duplicate node ids instead of letting discoverability depend on payload order
- a registry-source snapshot must keep each top-level node's `last_signed_event_at` sane: it cannot jump too far into the future, cannot run later than the snapshot's own `exported_at`, and cannot run earlier than that node's own signed announcement timestamp
- a registry-source snapshot must not omit `last_signed_event_at` for a signed top-level node
- a registry-source snapshot must keep each top-level node's `last_seen` sane: it cannot jump into the future, run later than the snapshot's own `exported_at`, or fall earlier than that node's own `last_signed_event_at`
- a registry-source snapshot must not present an unsigned top-level node under a `node_id` that also carries a current manifest; manifest-protected top-level nodes must stay signed
- a registry-source snapshot must keep each signed top-level node internally honest at all times: the current top-level node must still verify as the signed announcement itself, except for the one allowed runtime drift from a later signed heartbeat, namely a changed `open` state
- a registry-source snapshot must keep each top-level manifest `stored_at` sane: it cannot jump into the future or run later than the snapshot's own `exported_at`
- a registry-source snapshot must keep each embedded top-level manifest internally valid: mutating a manifest without a matching manifest signature must still be rejected even if the outer registry envelope is re-signed
- a registry-source snapshot must keep each embedded manifest timeline sane: `manifest.issued_at` cannot run later than that manifest's `stored_at` or later than the snapshot's own `exported_at`
- a registry-source snapshot must keep each `identity_events[].recorded_at` sane: it cannot jump into the future or run later than the snapshot's own `exported_at`
- a registry-source snapshot must keep each `identity_events[].signed_at` sane: it must parse as a real timestamp and cannot run later than that event's own `recorded_at`
- a registry-source snapshot must not replay the same signed identity event multiple times with different `event_id` values
- a registry-source snapshot must keep `identity_events` contiguous by `event_id`; gaps in the signed event log are rejected
- a registry-source snapshot must not repeat the same manifest `node_id` in its top-level `manifests` list; downstream import rejects duplicate manifest records instead of letting node visibility depend on which conflicting manifest lands last
- a registry-source snapshot must not repeat the same `(node_id, node_public_key)` pair in its `identity_records` list; downstream import rejects duplicate identity records instead of letting proof metadata depend on which conflicting record lands last
- a registry-source snapshot must keep `identity_records` and `identity_events` aligned on key membership; downstream import rejects snapshots where a key has signed events but no corresponding identity record summary
- a registry-source snapshot must keep each `identity_records[].event_count` aligned with the actual number of matching `identity_events`; downstream import rejects inflated or stale proof counters instead of letting signed metadata overstate how much history a node key really has
- a registry-source snapshot must also keep each `identity_records[].first_seen`, `last_seen`, and `scope` aligned with the matching `identity_events`; downstream import rejects stale timeline or scope summaries instead of letting signed proof metadata misstate how long or where a node key has really been seen
- when a current manifest is present for a node, a registry-source snapshot must also keep `identity_records[].status` aligned with that manifest: keys still present in the current manifest must report the manifest's active/revoked state, and records cannot stay `active` after the current manifest has dropped the key
- a registry-source snapshot must also keep each signed top-level node aligned with current manifest visibility; downstream import rejects signed node summaries whose current manifest key is missing, revoked, expired, or no longer matches the delegation/capability shape of the node summary
- a registry-source snapshot must also keep each signed top-level node aligned with `identity_records`; downstream import rejects signed node summaries whose `(node_id, node_public_key)` has no matching identity-record proof summary
- a registry-source snapshot must keep its `identity_events` list strictly increasing by `event_id`, with nondecreasing and not-too-far-future `recorded_at`, and `latest_identity_event_id` must match that tail; downstream import rejects out-of-order, time-skewed, duplicated, inflated, or stale identity-log pointers instead of letting mirror status misreport the chronology or amount of event evidence
- `/health` exposes storage mode plus mirrored-source counts, curated active index counts, curated promotion counts, curated override counts, directory claim counts, trust-claim counts, and registry metadata
- unsigned legacy nodes remain accepted during early `v0.1` development
- if `P4P_BACKUP_REGISTRIES` is omitted, `/registry-info` falls back to the current registry only
- `/registry-info` is advisory in `v0.1`; clients should merge it with pinned local seeds rather than treating it as authoritative
- this is the reference registry, not a central order platform
