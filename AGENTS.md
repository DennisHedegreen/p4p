# AGENTS — P4P

Read `README.md`, `SPEC.md`, and `ARCHITECTURE.md` before touching anything.

## What this project is

P4P is currently an open protocol and reference implementation for direct restaurant-customer discovery and ordering.

Treat `v0.1` as protocol proof, not a startup app suite.

Current reading:

- status: advanced prototype
- public claim: public protocol proof + controlled live pilot next
- `demo-node/` is proof and lab infrastructure, not a live restaurant node
- `pilot-node/` is the only live-directed node shape in this repo

## Canonical build target

Build the public proof in this order:

1. `registry/` first
2. `demo-node/` second
3. `client/` third

Treat `pilot-node/` as the separate next gate for controlled live-pilot work.

Legacy product folders such as `tracker/`, `tablet-app/`, and `customer-app/` are not the current build target unless explicitly reactivated.

## v0.1 scope

v0.1 is strictly:
- registry announce
- registry heartbeat
- registry discover
- registry failover metadata
- node menu endpoint
- node order endpoint
- minimal web client
- backup registry failover

The active `dev` branch may also contain identity, manifest, mirroring, moderated-directory, trust-claim, and module-design layers.

Treat those as prototype support layers unless the docs explicitly promote them into the current public proof claim.

No payment. No delivery. No auth. No reviews. No production security.

Do not add anything outside this scope without being asked.

## Rules

- Keep the implementation minimal and inspectable
- Prefer web-first demo flow over app-install friction
- Preserve direct client-to-node communication after discovery
- Registry must not become an order relay
- Keep the public claim narrower than the full `dev` runtime
- `demo-node/` is proof-only
- `pilot-node/` is the only node surface that may move toward real restaurant orders
- Data contracts in `SPEC.md` are the source of truth
- Service boundaries in `ARCHITECTURE.md` are the architectural source of truth
- Security weaknesses in `v0.1` are intentional and must be documented, not hidden
- Keep private strategy, outreach, field briefs, personal planning, and financial notes outside this repo

## Reference stack

| Layer | Tech |
|---|---|
| Registry | FastAPI |
| Demo node | Python |
| Client | Static HTML + JavaScript |
| Storage | In-memory for v0.1 |

## What not to do

- Do not drift back into full marketplace scope
- Do not add payment
- Do not add delivery logic
- Do not add account systems
- Do not hide protocol assumptions behind framework magic
- Do not treat local public snapshot branches such as `public-main` as normal integration branches
- Do not commit private go-to-market plans, contributor-invite plans, personal notes, or field documents
