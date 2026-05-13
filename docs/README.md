# P4P Docs

This folder holds the concrete contract layer for `v0.1`.

Use it when building code, validating payloads, or comparing independent implementations.

The public reading of these docs is still narrow:

- public protocol proof now
- controlled live pilot next
- no silent promotion of `v0.2` design material into the active `v0.1` claim

If you arrived here from GitHub and need the short orientation first, read `docs/GITHUB-READER-GUIDE.md` before diving into schemas or flow packs.

## Structure

- `schemas/`
  JSON Schema files for core protocol objects, discover views, and reference inspection responses.
- `examples/`
  Canonical example payloads for requests and responses, plus synthetic
  photo-map menu fixtures under `examples/menu-photo-map-fixtures/` and
  generated food/ingredient image fixtures under `examples/food-image-fixtures/`.
- `MODULE-PROVIDERS.md`
  Planned `v0.2` model for module providers, module manifests, data access, signatures, and trust claims.
- `COMMUNITY-MODULES.md`
  GitHub-first guide for building, labeling, testing, and publishing P4P-compatible modules without treating every module as official or production-ready.
- `modules/`
  Human-readable reference pages for every current module manifest, including purpose, status, data access, boundaries, and local test paths.
- `providers/`
  Human-readable reference pages for every unique current provider manifest identity in the reference catalog.
- `MODULE-RULES.md`
  Practical boundary rules for deciding what is core, what is a module, and what registries must not control.
- `EVENT-CATALOG.md`
  Planned `v0.2` canonical event-name list shared by module manifests, flows, and typed runtime events.
- `MODULE-EXECUTION-CONTRACT.md`
  Planned `v0.2` execution contract for module lanes, event/result shape, permissions, fallback policy, and idempotency.
- `PAYMENT-ADAPTER-STANDARD.md`
  Public guardrail for payment modules: P4P routes payment requests to adapters but does not become a payment provider.
- `WHITEPAPER-v0.1.md`
  Working public whitepaper for the prototype: problem, scope, core protocol, module model, payment boundary, trust/federation direction, non-goals, and roadmap.
- `MONEY.md`
  Active rule for menu currency, integer minor-unit prices, order totals, and payment-adapter amount boundaries.
- `MENU-PHOTO-MAP-TEST-TARGETS.md`
  Manual external menu targets for testing photographed/paper-menu mapping without copying third-party assets into the repo.
- `FIRST-FLOWS.md`
  First concrete module-flow sketches for printer, payment, AI-menu fallback, and duplicate-protection behavior.
- `ORDER-CONSENT.md`
  Rule for menu-only, test-order, and live-order node states.
- `NODE-IMPLEMENTER-KIT.md`
  Short packet for independent node builders and interop sessions.
- `NODE-OPERATOR-LITE.md`
  Reference node-owned operator surface for controlling order mode, modules, and registry health.
- `LANGUAGE-PACKS-v2.md`
  Next-step spec for moving operator/public shell copy into installable language-pack JSON layers while keeping the locale engine in code and module/provider text in manifests.
- `NODE-IDENTITY.md`
  Ed25519 signed announcements and signed heartbeats for protecting node metadata updates.
- `PROOF-STATUS.md`
  Current dated proof checkpoint for public hosting behavior, browser verification, and source-of-truth alignment.
- `GITHUB-READER-GUIDE.md`
  Short map for GitHub readers who need the repo to explain itself quickly before they read the deeper docs.
- `RELEASE-NOTES.md`
  Short checkpoint and release-candidate notes used before cutting a proof-safe story to `main`.
- `RELEASE-PLAN.md`
  Branch, tag, and alpha milestone rules for publishing the work without changing the active protocol contract.

## Rule

`SPEC.md` explains the protocol in prose.

`docs/schemas/` and `docs/examples/` make that prose operational.

`schemas/node.schema.json` is the node-announcement contract.

`schemas/node-delegation.schema.json` is the optional root-signed delegation object for operational node keys.

`schemas/node-manifest.schema.json` is the root-signed lifecycle document for operational node keys.

`schemas/node-manifest-request.schema.json` is the registry request shape for posting a node manifest and optional root-rotation proof.

`schemas/node-root-rotation.schema.json` is the previous-root-signed proof object that allows a registry to accept a new root key for an existing `node_id`.

`schemas/node-view.schema.json` is the discover-response view with registry-added fields such as `last_seen` and `distance_km`.

`schemas/directory-node-view.schema.json` is the moderated-directory view layered on top of discoverability.

`schemas/directory-response.schema.json` is the separate moderated public directory surface.

`schemas/directory-claims.schema.json` is the inspection contract for persisted moderated-directory claims.

`schemas/trust-claims.schema.json` is the inspection contract for signed trust claims that can travel between registries without becoming node identity truth.

`schemas/registry-source.schema.json` is the read-only registry snapshot contract for later mirroring, umbrella ingestion, and signed source export.

`schemas/registry-source.schema.json` now also carries `registry_metadata`, so runtime scope and capability declarations travel with the exported snapshot.

`schemas/provider-manifest.schema.json`, `schemas/module-manifest.schema.json`, `schemas/module-event-name.schema.json`, and `schemas/module-result-event.schema.json` are the first concrete `v0.2` draft shapes for provider identity, module execution contracts, canonical event names, and typed module result events.

`schemas/node-module-declaration.schema.json` is the small bridge shape for what a node may later announce publicly about one active module without embedding the full provider or module manifest inline in node metadata.

`schemas/curated-promotions.schema.json` is the inspection contract for persisted curated-promotion decisions: why a mirrored source was promoted or denied, and which node ids are currently exposed through the curated active index.

`schemas/curated-overrides.schema.json` is the inspection contract for manual allow/deny overrides that sit above automatic promotion records but below identity truth.

The current discover view also carries provenance fields so clients can tell whether a result is local or mirrored, whether mirrored visibility comes from a trusted upstream or trusted relay, and which original plus relay registries are involved.

The runtime now distinguishes:

- raw mirror cache: imported evidence only
- curated active index: policy-promoted mirrored state that may appear in `GET /discover`
- curated promotion records: persisted decisions explaining why mirrored evidence was promoted or denied
- curated overrides: persisted allow/deny visibility decisions that may steer curated discoverability without rewriting source truth
- moderated directory: a separate public surface that may annotate or hide otherwise discoverable nodes without changing raw evidence or the curated active index
- trust claims: signed transportable positive annotations that may be projected into the moderated directory without changing `GET /discover`

Registry capability metadata now also distinguishes between:

- `can_curate_active_index`
- `can_moderate_directory`
- `can_issue_trust_claims`

The discover contract is intentionally tied only to local canonical nodes plus the curated active index. Raw mirrored cache is not a discover surface by itself.

`GET /directory` is intentionally a separate surface from `GET /discover`. It can carry claims like `reviewed`, `verified`, `hidden`, `spam`, or `local_only` without rewriting node identity or upstream source truth.

Signed trust claims are a separate layer from local directory claims. They may travel between registries and annotate `GET /directory`, but they do not change node identity, raw source evidence, or operational discoverability.

`examples/registry-source-with-trusted-mirrors.json` shows the first umbrella-style re-export shape: local state stays canonical at the top level, and trusted mirrored upstreams travel as nested source snapshots instead of being flattened.

If a code implementation disagrees with these files, fix the code or tighten the spec.

The current schemas and examples are `v0.1`.

Repo alpha releases do not automatically change `protocol_version`.

The module-provider model is design documentation for `v0.2`; it does not change the active `v0.1` payload contracts.

The module-execution contract and first-flow pack are also `v0.2` design documents. They describe how later runtime modules should behave without changing the active `v0.1` node, registry, menu, or order payload shapes.

`modules/` contains reference manifests for the planned `v0.2` provider/module shape. In the active `v0.1` wire contract, node-announced module ids are still opaque strings only.

Loopback HTTP is allowed only for local reference development where the spec explicitly says so.
