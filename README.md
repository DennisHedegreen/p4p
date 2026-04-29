# P4P

An open protocol for direct restaurant-customer discovery and ordering without a platform middleman.

P4P is a phone book, not a marketplace.

P4P is the socket, not the appliances.

The core idea is simple:

basic restaurant-customer contact should not require a platform taking rent on first contact.

Companies are allowed to build on top.

But the connection itself should stay open.

## What v0.1 is

The current target is not a full product stack.

It is a narrow reference implementation that proves this loop:

1. A node announces itself to one or more registries
2. A client discovers the node through a registry
3. The client fetches the menu directly from the node
4. The client sends an order directly to the node
5. The client fails over to a backup registry for discovery if the primary disappears

Nodes also announce `order_mode` so discovery is not confused with permission to receive orders.

The reference demo uses `test` orders.

Real restaurant order intake belongs behind explicit node-operator activation.

Nodes also sign announcements and heartbeats with an Ed25519 node key in the reference implementation.

That protects a signed `node_id` from simple unsigned takeover and from older signed replays at the same registry once a newer signed event has been accepted, but it does not certify the restaurant.

The current skeleton can also carry an optional root-signed delegation, so a restaurant root identity can authorize a day-to-day operational node key for one `node_id` without giving the registry any private keys.

The next identity slice now also exists: a root-signed node manifest can be posted to registries so revoked operational keys disappear from discovery and a new root key can take over through a previous-root rotation proof.

In `v0.1`, failover means client failover across registries while nodes dual-register to both.

It does not mean automatic registry-to-registry synchronization.

## Long-Term Network Shape

`Pizza4People` is the first concrete proof network.

`Protocols4People` is the broader umbrella direction.

The long-term shape is not one flat global registry run as a permanent center.

It is a federation of scoped registries that may exist at different levels:

- umbrella registry
- vertical registry
- country registry
- local or community registry

Example direction:

`Protocols4People -> Pizza4People -> Denmark -> local city or region registries`

The same node may appear in more than one scope at the same time.

A scoped registry is a discovery surface, not a second identity authority.

Node identity should still come from node keys, root keys, delegations, and node manifests.

`v0.1` does not implement full scoped federation or a complete trust ecosystem yet, but the reference runtime now includes the first moderated directory skeleton on top of discoverability.

## Beyond Pizza

`P4P` should not be read as "pizza software forever."

It is the first concrete proof profile.

The broader direction is `Protocols4People`:

- a small shared protocol core
- multiple vertical profiles
- a broad module economy
- scoped registries at umbrella, vertical, country, and local levels

In that reading:

- `Pizza4People` is one vertical profile
- ticketing could become another
- retail goods could become another
- local services could become another

The important discipline is to keep the shared core small.

The core should solve:

- identity
- announce
- discovery
- current state
- manifests
- feeds or snapshots
- direct endpoint-to-endpoint contact

The current reference runtime now includes a first registry snapshot surface for later mirroring and umbrella ingestion, mirror ingest, and a separate moderated directory layer above discoverability.

The moderation capability is now explicit too: curating the active index and moderating the public directory are no longer treated as the same registry power.

The runtime now also includes the first signed trust-claim skeleton: a registry can issue a signed `reviewed` or `verified` claim, another registry can import it, and the moderated directory can project that claim without turning it into node identity or ordinary discoverability.

It now also includes the first mirror consumer, so one registry can import and cache another registry's signed source snapshot and expose mirrored nodes through normal discovery.

The current runtime can also poll configured upstream registries automatically, but it still treats mirrored state as a local cache layer rather than a full federation graph, and it does not re-export mirrored cache as fresh source of record.

Vertical profiles should then define domain-specific objects and flows.

Modules should carry everything else:

- payment
- delivery
- booking
- invoicing
- trust
- inventory
- POS
- scanning
- supplier integrations

That same module economy may also reach backward into production and supply chains, not only forward into customer checkout.

## Reference implementation

- `registry/` — FastAPI registry server
- `demo-node/` — simulated restaurant node
- `pilot-node/` — first controlled live restaurant node foundation
- `client/` — minimal web client
- `demo-node/operator.html` — demo-only node operator surface
- `SPEC.md` — canonical protocol spec
- `ARCHITECTURE.md` — long-term system boundaries and module model
- `ROADMAP.md` — build sequence from local proof to modules and trust
- `PILOT-LIVE.md` — first live restaurant pilot scope, topology, and stop conditions
- `PROOF.md` — public online proof target for `v0.1`
- `docs/` — schemas and example payloads for the core contract
- `docs/RELEASE-PLAN.md` — branch, tag, and alpha milestone rules
- `docs/PUBLIC-GITHUB.md` — safe public/private GitHub split for publishing
- `modules/` — reference module manifests and examples
- `deploy/` — public proof deployment notes and example runtime config
- `scripts/public-audit.sh` — local pre-publication audit helper
- `TEST-GUIDE.md` — practical manual and automated testing flow for `v0.1`
- `TEST-GUIDE-OPERATOR.md` — short Danish operator version of the testing flow

`lab/` lives beside the protocol implementation as a local debug harness.

It is not part of the protocol surface.

The reference node operator is also not part of the public protocol surface.

It is the first restaurant-owned control layer for toggling node state, order mode, modules, and registry health.

## Current stance

- `v0.1` proves discovery and direct ordering
- `protocol_version: "0.1"` is separate from repo alpha release tags
- `main` should stay showable; `dev` can move faster
- public `main` and private `dev` must live in separate GitHub repositories, because GitHub visibility is repository-level
- no protocol-managed payment
- no delivery
- no user accounts
- no review system
- no production security
- no broad production restaurant operations yet
- `pilot-node/` is the controlled live-pilot target, not the demo node
- no CVR-backed restaurant verification
- modules are opaque ids only, not executable contracts

## Protocol stance

- core discovery should stay open
- direct ordering should work without commercial permission
- registries may be run by anyone
- modules may be free or paid
- menu is core, not a module
- companies may participate, but should not own the base contact layer

## Why now

Just Eat exits Denmark on April 30, 2026.

That makes the timing window real, but the immediate goal is proof, not product theater.

## Legacy project folders

`tracker/`, `tablet-app/`, and `customer-app/` remain as broader product-track placeholders.

They are not the canonical build target for `v0.1`.

See `SPEC.md` for the working protocol definition.

See `ARCHITECTURE.md` for the proper long-term build shape.

## Publishing

The safe public model is:

- public repo: `github.com/DennisHedegreen/p4p`
- private repo: `github.com/DennisHedegreen/p4p-dev`

Do not make a repository public while it still contains a private `dev` branch or private reachable history.

Before publishing a public branch, run:

```sh
bash scripts/public-audit.sh
```

See `docs/PUBLIC-GITHUB.md` for the full split and release sequence.

## License

Code is licensed under MIT.

Protocol text and documentation are licensed under CC BY 4.0.

See `LICENSE.md`.
