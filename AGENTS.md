# AGENTS — P4P

Read `README.md`, `SPEC.md`, and `ARCHITECTURE.md` before touching anything.

## What this project is

P4P is currently an open protocol and reference implementation for direct restaurant-customer discovery and ordering.

Treat `v0.1` as protocol proof, not a startup app suite.

## Canonical build target

Build in this order:

1. `registry/` first
2. `demo-node/` second
3. `client/` third

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

No payment. No delivery. No auth. No reviews. No production security.

Do not add anything outside this scope without being asked.

## Rules

- Keep the implementation minimal and inspectable
- Prefer web-first demo flow over app-install friction
- Preserve direct client-to-node communication after discovery
- Registry must not become an order relay
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
- Do not commit private go-to-market plans, contributor-invite plans, personal notes, or field documents
