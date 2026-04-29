# P4P Roadmap

This roadmap replaces the old linear `v0.1 -> v0.2 -> v0.3` list.

The project has already moved beyond a simple local proof.

The current code now contains early versions of identity, delegation, manifests, registry source export, mirror ingest, mirror sync, curated active index, moderated directory, and signed trust claims.

Those pieces are useful.

They are not all mature enough to be called production protocol guarantees.

The right roadmap is therefore gate-based:

- keep the core protocol small
- make the first real restaurant pilot safe
- harden trust and federation before making broad claims
- keep the larger Protocols4People direction visible without widening the pizza core too fast

## 1. Vision

P4P is the first concrete vertical proof inside a broader Protocols4People direction.

The immediate proof is restaurant discovery and direct ordering.

The long-term protocol family should support:

- a small shared core
- multiple vertical profiles
- optional modules
- scoped registry federation
- direct endpoint-to-endpoint contact
- later supply-chain and business-to-business flows

The core political and technical rule remains:

no platform should own a relationship two parties can maintain directly through an open protocol.

For Pizza4People, that means:

`Client -> Registry -> Node`

only for discovery.

After discovery:

`Client -> Node`

for menu, order, and restaurant-owned operational flow.

The registry must never become:

- order broker
- payment processor
- menu host
- customer account owner
- restaurant operations dashboard
- certification authority for everything

## 2. Current Reality

Status: advanced prototype.

The local proof is green.

The reference implementation already proves:

- node announce
- signed announce
- signed heartbeat
- direct menu fetch
- direct order POST
- client failover across registries
- order consent through `order_mode`
- node operator lite
- root-signed operational delegation
- root-signed node manifest
- narrow root rotation proof
- identity-log inspection
- optional SQLite-backed registry persistence
- registry source export
- registry source import
- mirror sync
- raw mirror cache vs curated active index
- curated promotion records
- curated allow/deny overrides
- moderated directory claims
- signed trust-claim skeleton
- scoped registry metadata
- trusted mirror re-export as nested upstream snapshots

This means the old roadmap understated the system.

But the system is not yet production-grade because:

- trusted registry URLs are not yet pinned to expected registry public keys
- signed trust claims are currently valid signatures, not yet trusted issuer guarantees
- the web client must treat all registry, node, and menu data as untrusted input
- docs still mix old version language with newer runtime reality
- demo-node is not a safe live restaurant node
- real restaurant order operation needs persistence, login, and order states

## 3. Release Names

Use release names to avoid pretending that every prototype layer is mature.

### `proof.1`

Public technical proof.

Can use a demo node.

Proves:

- discovery
- direct menu
- direct test order
- signed node identity
- registry failover

Does not prove:

- real restaurant operation
- live order handling
- production security
- trusted federation
- module economy

### `pilot.1`

First real restaurant pilot.

Uses one real restaurant node and real live pickup orders.

Must prove:

- a real restaurant can run or control its own node
- orders go directly to that node
- registry A and registry B can both discover the same node
- registry failure does not break discovery
- registry never sees order contents

This is the next important gate.

### `alpha.2`

Protocol hardening alpha.

Turns the first pilot lessons into cleaner contracts.

Focus:

- production-shaped node operator
- stable order-state contract
- registry key pinning
- trusted issuer lists
- safer client rendering
- clearer schemas and examples

### `beta.1`

Interoperability beta.

A second implementation should be able to build against the docs.

Focus:

- independent registry implementation
- independent node implementation
- independent client implementation
- stable schema validation
- documented migration rules

### `v1.0`

Stable first release.

P4P reaches `v1.0` only when an independent implementer can build a registry, node, client, and at least one module without asking one company for permission.

## 4. Gate A: Public Core Proof

Status: mostly done locally.

Purpose:

show the core loop without claiming production readiness.

Minimum surfaces:

- one public client
- one primary registry
- one backup registry
- one test node
- HTTPS for public endpoints
- signed node announcements
- signed heartbeats
- explicit `order_mode: "test"`

Acceptance:

- client discovers node through primary registry
- client fetches menu directly from node
- client sends test order directly to node
- primary registry can be stopped
- client discovers the same node through backup registry
- registry does not receive menu or order payloads
- operator UI is not publicly exposed

This gate may be recorded as a proof video.

It is no longer the main goal if a real restaurant pilot is available.

## 5. Gate B: Real Restaurant Pilot

Status: next target.

Purpose:

move from demo to controlled live restaurant use without widening scope.

Topology:

- `client.pizza4people.com`: public web client
- `registry-a.pizza4people.com`: primary registry, likely Hetzner
- `registry-b.pizza4people.com`: backup registry, Dennis-owned server
- restaurant node: owned or controlled by the restaurant

The restaurant node may initially run on a small VPS or restaurant-controlled machine.

Architecturally it must be treated as the restaurant's node:

- restaurant-owned menu
- restaurant-owned order history
- restaurant-owned operator access
- restaurant-owned node key material
- direct client-to-node order intake

Pilot scope:

- one restaurant
- pickup only
- pay at pickup
- no delivery module
- no online payment module
- no customer accounts
- no loyalty
- no review system
- no broad federation claims

The pilot should prove:

- a real customer can discover the restaurant without a platform account
- a real menu is fetched directly from the restaurant node
- a real pickup order reaches only the restaurant node
- the restaurant can accept, reject, mark ready, and close orders
- backup registry discovery works if primary registry is unavailable
- the system can be stopped safely if anything fails

Stop conditions:

- orders are not visible to the restaurant
- duplicate orders cannot be distinguished
- customer contact is exposed outside the node
- operator login is broken or exposed
- registry receives order contents
- live/test state is unclear to customers
- restaurant cannot turn ordering off quickly

## 6. Gate C: Pilot Node

Status: foundation built.

Purpose:

replace demo-node for real restaurant operation.

Required capabilities:

- persistent menu configuration: first version exists
- persistent order storage: first version exists
- operator login: token-protected endpoints exist
- order dashboard: API exists, UI still needed
- order states: `new`, `accepted`, `rejected`, `ready`, `completed`, `cancelled`: first version exists
- order timestamp and order id: first version exists
- customer name and contact stored only in node: first version exists
- clear pickup/payment wording: first version exists
- live/test/menu-only/closed controls: first version exists
- registry health view: API exists, UI still needed
- manual reannounce: first version exists
- signed announcements and heartbeats: first version exists
- root key and operational key support
- exportable backup of local node data

Recommended first storage:

- SQLite

Do not add:

- payment processing
- delivery dispatch
- customer accounts
- restaurant analytics
- review capture
- centralized order relay

The node operator layer is not a protocol module.

It is the restaurant-owned control plane for one node.

## 7. Gate D: Client Hardening

Status: required before real pilot.

Purpose:

make the browser client safe enough for untrusted registry and node data.

Required:

- stop rendering untrusted data through raw `innerHTML`
- escape or DOM-build all node, menu, module, and endpoint text
- show live/test/menu-only state clearly
- show pay-at-pickup clearly
- show which registry answered discovery
- preserve failover behavior
- keep direct client-to-node menu and order flow

The public client should not pretend to be a full marketplace.

It is a reference client for direct discovery and ordering.

## 8. Gate E: Deployment Spine

Status: partially documented.

Purpose:

make the live topology repeatable.

Required deployment pieces:

- Caddy or nginx reverse proxy
- systemd services for registries
- systemd service for restaurant node
- env examples for registry A
- env examples for registry B
- env example for restaurant node
- SQLite paths outside the repo
- stable node key files outside the repo
- stable registry signing key files outside the repo
- log inspection commands
- restart commands
- backup commands

First real topology:

- Hetzner: primary registry and public client
- Dennis server: backup registry
- restaurant-controlled host: restaurant node

The first live pilot may still use a hosted node if the restaurant cannot host yet.

If that happens, document it honestly as a hosted restaurant node, not as full self-hosting.

## 9. Gate F: Trust Hardening

Status: prototype exists; hardening required.

Purpose:

make signed registry and trust data mean what the words imply.

Required before broad trust/federation claims:

- trusted upstream entries bind registry URL to expected registry public key
- registry source import verifies both signature and expected key when configured
- trust-claim issuer lists bind issuer URL to expected public key
- imported trust claims distinguish `valid_signature` from `trusted_issuer`
- directory projection only shows trust claims from trusted issuers by default
- client-facing labels avoid overclaiming trust
- docs describe self-signed, signed, trusted, and verified as separate states

Do not call a registry source trusted merely because:

- it is signed by a key it supplied itself
- it claims a trusted URL in its payload

Do not call a trust claim trusted merely because:

- its signature validates against the public key inside the same claim

Trust requires a pinned or otherwise accepted relationship between identity and key.

## 10. Gate G: Federation Maturity

Status: early skeleton exists.

Purpose:

turn current mirror and directory code into a real federation model.

Current skeleton:

- raw mirror cache
- curated active index
- promotion records
- manual overrides
- moderated directory
- signed trust claims
- nested trusted mirror re-export
- scoped registry metadata

Still needed:

- registry key pinning
- trust-list format
- issuer-list format
- replay rules for imported registry sources
- conflict policy when the same node appears in several scopes
- event-feed or snapshot cadence rules
- moderation audit model
- governance notes for umbrella vs vertical vs country vs local registry roles

Federation must preserve the rule:

scope does not create identity.

Node identity still comes from:

- node key
- root key
- delegation
- node manifest
- signed lifecycle events

Registries carry, filter, mirror, or moderate what they show.

They must not become second identity owners.

## 11. Gate H: Module Contract

Status: opaque module ids only.

Purpose:

define the first real module economy without making modules mandatory.

First module model should define:

- provider manifest
- module manifest
- module id
- provider id
- module type
- version
- required node configuration
- customer data required
- node data required
- test/live readiness
- signature

First practical module examples:

- `p4p.payment.cash`
- `p4p.payment.mobilepay`
- `p4p.pos.printer`
- `p4p.delivery.own-courier`
- `p4p.trust.cvr-claim`

Rules:

- menu endpoint is core, not a module
- ordering is core, not a module
- payment is a module
- delivery is a module
- reviews are modules
- trust verification is claim-based, not permission-based
- no module may be required for basic discovery and pickup ordering

## 12. Gate I: Independent Implementation

Status: future.

Purpose:

prove P4P is a protocol, not one codebase.

Requirements:

- one independent registry can pass core contract tests
- one independent node can announce, heartbeat, expose menu, and receive orders
- one independent client can discover and order directly
- JSON schemas are stable enough to build against
- examples match real runtime behavior
- compatibility notes exist for breaking changes

This is the gate that turns P4P from prototype into credible open protocol.

## 13. Gate J: Protocols4People

Status: vision layer.

Purpose:

make the broader protocol family real without bloating Pizza4People.

The shared core should stay responsible for:

- identity
- announce
- discovery
- current state
- manifests
- feeds or snapshots
- direct endpoint-to-endpoint contact

Vertical profiles should define domain objects:

- restaurant menus and orders
- ticketing events and tickets
- retail inventory and checkout
- local services and bookings
- supplier and procurement flows

Modules should carry optional business functions:

- payment
- delivery
- scanning
- verification
- accounting
- inventory
- loyalty
- support integrations

Do not widen the core every time a new market appears.

Create a new vertical profile instead.

## 14. This Week Build Order

If the real restaurant can wait one week, use the week to build a controlled live pilot.

Order:

1. Rewrite roadmap and public claims so they match current reality.
2. Define `pilot-node` scope.
3. Build persistent orders with SQLite.
4. Build operator login and order dashboard.
5. Add order states.
6. Harden client rendering.
7. Add deployment env and systemd examples for restaurant node.
8. Dry-run full topology with fake restaurant data.
9. Load real menu.
10. Launch only when stop conditions are clear.

Do not spend this week expanding trust federation.

The first live pilot needs operational reliability more than broader federation claims.

## 15. Definition Of A Proper First Version

The first proper version is not the one with the most features.

It is the one where one real restaurant can use the protocol without the architecture lying.

Minimum:

- restaurant node receives real pickup orders
- restaurant can manage order state
- restaurant can turn ordering off
- registry does not see order contents
- client can fail over between two registries
- all public surfaces use HTTPS
- node identity is signed
- orders persist across restart
- customer data stays in the node
- docs say exactly what is proven and what is not

That is the first serious P4P version.

Everything else can build from there.
