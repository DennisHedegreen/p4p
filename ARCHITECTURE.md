# P4P Architecture

This document explains how P4P should be built if the goal is a durable open protocol rather than a short-lived demo.

Read this together with `SPEC.md`.

`SPEC.md` defines the contract.

`ARCHITECTURE.md` defines how to implement the contract without collapsing back into platform capture.

This file is not the current public proof claim.

If documents overlap:

- `SPEC.md` wins on normative wire contract
- `PROOF.md` wins on what is publicly claimed right now
- `ARCHITECTURE.md` wins on service boundaries and anti-capture design

## 1. Architectural Goal

P4P should make one thing cheap, open, and hard to capture:

direct restaurant-customer discovery and ordering.

Everything beyond that is optional.

That means the system must be designed so that:
- core discovery is interoperable
- direct ordering works between independent implementations
- no single registry is required forever
- no company owns the protocol boundary
- commercial layers can exist without becoming mandatory

## 1.1 Protocol Family Direction

`P4P` is the first concrete vertical proof.

It should not be mistaken for the full long-term ceiling of the system.

The broader direction is better read as `Protocols4People`:

1. a shared protocol core
2. multiple vertical profiles
3. a module economy on top
4. scoped registry federation
5. later supply-chain use beyond customer checkout

In that model, pizza is only the first proof profile.

Later profiles could describe:

- ticketing
- retail goods
- local services
- supplier and procurement flows

The architectural discipline is:

do not keep widening the core every time a new market appears.

The core should stay responsible only for:

- identity
- announce
- discovery
- current state
- manifests
- feeds or snapshots
- direct endpoint-to-endpoint contact

Vertical profiles should define domain-specific objects and flows.

Modules should carry the rest.

## 2. System Layers

P4P should be read as five separate layers.

### 2.1 Core Protocol

The protocol itself:
- node metadata
- optional signed node announcements
- optional signed node heartbeats
- registry endpoints
- node endpoints
- failover behavior
- versioning rules

This layer must stay small, documented, and stable.

### 2.2 Reference Implementations

Concrete code proving the protocol works:
- `registry/`
- `demo-node/`
- `client/`

These are examples, not the protocol itself.

They should stay simple enough that others can reimplement them independently.

### 2.3 Node Operator Layer

The node operator layer is the restaurant's private control surface.

It is where a restaurant manages:
- menu and prices
- open or closed status
- whether the node is menu-only, test-order, or live-order enabled
- incoming orders and order state
- registry health
- node configuration
- keys, certificates, and signing material
- active modules and provider credentials

This layer belongs with the node.

It must not move into the registry.

The node operator layer may control modules, but it is not itself a protocol module.

The reference demo node exposes a small operator UI only to prove this boundary.

That UI is implementation-specific and demo-only.

### 2.4 Trust and Security Layer

This is not part of the minimal core in `v0.1`, but it is a real future layer:
- node verification
- registry trust
- signatures
- CVR binding
- web-of-trust
- reputation and abuse handling
- provider manifests
- trust claims

This must be added as an extension layer, not by turning the registry into a gatekeeper.

The current reference implementation has the first node-identity skeleton:

- a node can generate or load an Ed25519 keypair
- the node signs announcements and heartbeats
- registries reject unsigned, tampered, or older signed updates to an existing signed `node_id`
- an optional root key can delegate announce/heartbeat rights to an operational node key for one `node_id`
- a root-signed node manifest can revoke operational keys or move the same `node_id` to a new root key through a previous-root rotation proof

That proves control of a node key.

It does not certify the restaurant.

The next identity direction is a node-owned, registry-recorded identity log plus delegated operational keys:

- node private keys stay with nodes and operators
- root keys may stay above day-to-day operational node keys
- a server only has private keys for nodes it actually hosts
- registries store public signed announcements and identity events
- registries do not hold node private keys
- registries may later sign identity-log snapshots for client verification

The intended verification chain is:

1. node signs announcement
2. registry verifies node signature
3. registry records identity event
4. registry signs log or snapshot later
5. client verifies both node signature and registry log signature

This is transparency, not central approval.

The current reference implementation includes only the first skeleton of that direction:

- verified signed announcements create identity events
- `GET /identity-log` exposes public identity records and events
- `GET /registry-source` exposes a full registry snapshot and may carry an optional registry signature
- `POST /registry-source/import` is the first mirror consumer for caching another registry's snapshot
- `POST /registry-sync` is the first automated fetch loop for configured upstream registries
- the log stores public keys and signatures, not node private keys
- mirrored state is still a simple cache layer, not yet a full federation or moderation system
- raw mirror cache and curated active index are now separate runtime layers
- imported mirror records are evidence by default and only become discoverable if explicit promotion policy moves them into the curated active index
- the registry now also keeps a persisted promotion-decision layer that explains why mirrored evidence was promoted or denied
- the registry may also keep a persisted override layer for scoped manual allow/deny decisions without rewriting identity or source history
- the registry may also keep a persisted directory-claim layer for public moderation above discoverability without rewriting identity, raw evidence, or curated promotion history
- the registry may also keep a persisted signed trust-claim layer for transportable positive directory annotations without turning claims into identity authority
- mirrored cache is not flattened into fresh local source-of-record data by the current runtime
- discover now reads only local canonical nodes plus curated mirrored entries, never raw mirror cache directly
- the first moderated directory surface now lives above discover and may be narrower than discover without changing the underlying operational discoverability view
- discover views now say whether a result is local or mirrored, whether it is visible because it is local, from a trusted upstream, or from a trusted relay, and which original plus relay registries are involved
- trusted mirror re-export now happens only as preserved nested upstream snapshots, not as flattened local source-of-record data
- registry runtime metadata can now declare `umbrella`, `vertical`, `country`, or `local` scope plus capabilities for onboarding, relay, curation, directory moderation, trust-claim issue, and re-export
- multi-node restaurant manifests are not implemented yet
- delegated backup-node behavior is not implemented beyond root-authorized role metadata

### 2.5 Optional Modules

Everything beyond discovery and direct ordering belongs here:
- payments
- delivery
- reviews
- loyalty
- identity
- accounting integrations
- Solid pod integration

Menu is not listed here because the public menu endpoint is core.

A menu importer may be a module.

The node's own menu endpoint is not.

Modules may be open or commercial.

No module should be required for baseline interoperability.

The long-term economic point is bigger than restaurant checkout.

If the protocol works, many independent companies should be able to build module businesses on top of it:

- payment
- delivery
- ticket scanning
- inventory
- invoicing
- trust and verification
- supplier sync
- sector-specific compliance

That same module layer may also extend backward into production and supply chains, not only forward into end-customer flows.

## 3. Canonical Service Model

The correct mental model is:

`Client -> Registry -> Node`

But only for discovery.

After discovery, the correct flow is:

`Client -> Node`

The registry must not become:
- order broker
- payment processor
- menu host
- review gatekeeper
- customer account owner

If that happens, P4P has already failed its own purpose.

The node operator layer sits behind the node:

`Node Operator -> Node`

That flow is private administration. It is not a public registry function and it is not a marketplace layer.

## 3.1 Registry Scope Model

The long-term registry model should be read as a federation of scopes, not one permanent global center.

Examples of scope:

- umbrella registry
- vertical registry
- country registry
- local or community registry

Examples of role:

- `Protocols4People` as an umbrella registry
- `Pizza4People` as a vertical registry
- `Pizza4People Denmark` as a country registry
- a city or regional pizza registry as a local registry

A backup registry is different.

A backup registry is redundancy for the same scope.

A sub registry is a narrower discovery surface inside a broader registry family.

The model is not strictly a tree.

The same node may appear in several registries at once:

- umbrella
- vertical
- country
- local

That makes the system closer to a scoped federation graph than to a single rooted directory.

The important rule is:

scope does not create identity.

Node identity still comes from:

- node keys
- root keys
- delegations
- node manifests

Registries may carry, mirror, filter, or moderate what they show.

They must not become second identity authorities.

## 4. Repo Shape

The long-term repo layout should be read like this:

- `SPEC.md`
  Protocol contract and versioning rules.
- `ARCHITECTURE.md`
  Service boundaries, extension model, and growth rules.
- `registry/`
  Reference registry implementation.
- `demo-node/`
  Reference restaurant node implementation.
- `client/`
  Reference web client implementation.
- `modules/`
  Reference examples and future optional protocol modules.
- `docs/`
  Future schemas, examples, governance notes, and migration notes.
- `PROOF.md`
  Public proof target for showing `v0.1` online.

Separate from the protocol room:

- `lab/`
  Local operator and debug harness for process control and multi-node testing.
  Not part of the protocol surface.

Legacy folders such as `tracker/`, `tablet-app/`, and `customer-app/` are earlier product-track placeholders and should not drive the core architecture.

## 5. Core Contracts

The core should remain small enough that it can be fully understood by reading a few contracts:

### 5.1 Registry Contract

The registry is responsible for:
- receiving announcements
- receiving heartbeats
- verifying signed announcements and heartbeats when a node uses a signing key
- answering discovery queries
- exposing backup-registry information
- later, recording public signed node identity events and signing identity-log snapshots

The registry is not responsible for:
- storing orders
- storing menus
- storing customer profiles
- mediating payment
- approving whether a restaurant accepts orders
- deciding which modules are allowed at runtime
- holding node private keys
- certifying that a node belongs to a real restaurant

### 5.2 Node Contract

The node is responsible for:
- exposing a menu
- receiving orders
- deciding whether it is open
- deciding and announcing its order mode
- holding restaurant-side operational data

The node should be replaceable.

A restaurant should be able to switch from one node implementation to another without leaving the protocol.

The node may also expose private operator controls.

Those controls are implementation-specific unless a later spec defines them.

They must not require the registry to mediate restaurant operations.

Order activation belongs here.

A restaurant can be discoverable as menu-only before it has approved live order intake.

Clients must respect the node's public `order_mode`, and nodes must reject orders when order mode is not `test` or `live`.

### 5.3 Client Contract

The client is responsible for:
- querying registries
- handling registry failover
- talking directly to nodes
- rendering menus and order flows

There may be many clients.

The protocol must not assume that only the official client exists.

For `v0.1`, registry failover should be read narrowly:

- clients fail over across registries for discovery
- nodes stay discoverable by announcing and heartbeating to more than one registry
- registry-to-registry synchronization is not part of this version

### 5.4 Node Operator Contract

The node operator layer is responsible for making a node usable by humans.

It should manage:
- menu edits
- open or closed state
- order mode: disabled, menu-only, test, or live
- order acceptance, rejection, and readiness
- registry readiness and failed-registry visibility
- module activation
- provider credentials
- node keys and certificates when trust layers arrive

The operator layer is allowed to be different across implementations.

The protocol should define what the public node exposes, not force every restaurant to use the same admin UI.

## 6. Data Ownership Rules

P4P only works if ownership stays where it belongs.

### Registry-owned data

The registry may hold:
- public node metadata
- `last_seen`
- discovery query context
- backup registry information
- public signed node identity events when the identity log is implemented
- current active index views derived from those identity events
- optional trust or moderation claims when a registry also acts as a curated directory

### Node-owned data

The node should hold:
- menu
- order history
- customer contact provided in the order flow
- restaurant-side operational state
- operator configuration
- module configuration and provider credentials
- node keys and certificates when enabled

Backup registries do not need node private keys.

Hosted backup nodes are different from backup registries.

If a provider hosts a backup node for a restaurant, the long-term model should use delegated operational keys instead of sharing the restaurant's root private key.

Local and development nodes may sign announcements, but their identities should not automatically enter a public identity log.

### Client-owned data

The client may hold:
- local preferences
- cached registry list
- cached menus
- temporary form state

This distribution is not just implementation detail.

It is the architecture's political and economic core.

## 6.1 History, Active Index, And Moderated Directory

A future umbrella or master registry should not collapse everything into one flat list.

It should keep at least three different layers:

1. raw identity history
2. current active index
3. moderated trust directory

### Raw identity history

This is the append-only source layer.

It should record:

- which node ids were ever announced
- which keys announced them
- which registries saw them
- later status such as active, revoked, or rotated

This layer should not pretend that an identity never existed.

### Current active index

This is the operational discovery layer.

It is derived from the current valid state:

- latest accepted announcement
- current heartbeat state
- current node manifest state
- current registry scope

This is the list normal clients search.

### Moderated trust directory

This is the organization or community layer on top.

It may add claims such as:

- reviewed
- verified
- hidden
- spam
- local-only

That layer may remove a node from a public directory view without erasing the underlying signed history.

This separation matters most for any future umbrella registry such as `Protocols4People`.

An umbrella registry may ingest broad history and maintain a current active index, while a moderated organization surface may still present a narrower public directory.

## 7. Module Boundary Rules

Modules should be designed as add-ons to the core, not replacements for it.

The node operator layer may enable, disable, and configure modules.

That does not make node operation a module.

Node operation is the local control plane for one restaurant node.

Good module boundaries:
- payment provider abstraction
- review provider abstraction
- identity provider abstraction
- delivery provider abstraction
- POS or printer integration
- verification and trust-list provider

Bad module boundaries:
- discovery hidden behind a proprietary API
- ordering only possible through one commercial relay
- registry access controlled by one vendor
- module certification controlled only by the registry

Rule:

If removing a module breaks basic discovery and ordering, that module was placed too deep.

## 8. Trust Model Roadmap

`v0.1` is intentionally insecure.

That is acceptable for proof.

It is not acceptable as the permanent architecture.

The next trust layer should be added in phases:

### v0.2

- node identity log
- registry-signed responses
- registry-signed identity-log snapshots
- provider manifests
- module declarations
- signed module manifests
- delegated backup-node keys
- broader trust lists
- optional node verification metadata
- basic rate limiting and abuse controls

### v0.3

- trust lists
- CVR-linked verification
- multi-registry reputation exchange
- scoped registries for umbrella, vertical, country, and local discovery
- clear separation between raw source history, active index, and moderated trust directory

### v1.x

- stronger federation rules
- migration guarantees
- clearer governance around module trust

The trust model should increase confidence without making central permission mandatory for the core protocol.

## 9. Reference Stack

For the durable implementation path, the default reference stack should be:

- `FastAPI`
- `Pydantic`
- `PostgreSQL` when persistence becomes necessary
- static web client before native apps
- `systemd` services or small VPS deployment before heavy orchestration

Why:
- easy to inspect
- fast to build
- strong contract typing
- low operational overhead
- simple for outsiders to understand and fork

## 10. Deployment Philosophy

The deployment model should also reflect the protocol's values.

### Registry

Should be easy to run:
- one small VPS
- one homelab box
- one community mirror

### Node

Should be able to run on:
- local machine
- tablet-adjacent device
- VPS
- tunnel-backed home setup

### Client

Should work in:
- browser first
- mobile wrapper later if needed

The protocol should not depend on app stores for existence.

## 11. Future-Safe Rules

When making architecture decisions, preserve these rules:

1. Keep the core small.
2. Keep the protocol readable.
3. Keep direct client-to-node ordering intact.
4. Keep registry power narrow.
5. Make room for both free and paid modules.
6. Avoid implementation choices that imply one official vendor forever.
7. Make replacement possible at every layer.

## 12. Build Order

If building properly, the order is:

1. Lock `SPEC.md`
2. Publish schemas and examples
3. Build `registry/`
4. Build `demo-node/`
5. Build `client/`
6. Add trust layer
7. Define first module interfaces

That is the correct sequence because protocol clarity matters more than UI polish.
