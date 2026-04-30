# P4P v0.1 — Specification

An open protocol for direct contact between restaurants and customers without a platform middleman.

P4P is the socket, not the appliances.

Status: Alpha. Not production-ready. Proves the concept.
Launch target: April 30, 2026
Author: Dennis Hedegreen, Hedegreen Research
License: MIT (code), CC BY 4.0 (specification)

---

## 1. Purpose

P4P proves one thing: a restaurant can be found by a customer without giving menu, order data, payment, or customer contact to a commercial platform.

P4P is a phone book, not a marketplace.

## 1.1 Protocol Family Direction

This `v0.1` specification is restaurant-specific.

That is deliberate.

`P4P` should be read as the first concrete vertical proof inside a broader `Protocols4People` direction.

The long-term idea is:

- one small protocol core
- many vertical profiles
- many module producers

This specification does not define ticketing, retail, or supply-chain objects.

It only proves the first restaurant profile cleanly.

## 2. Actors

**Node**: A restaurant announcing itself. Can run on a tablet, local server, VPS, or behind a tunnel. Exposes menu and order endpoints.

**Registry**: A public phone book of active nodes. Can run on any server. Multiple registries can exist in parallel and mirror one another. The same protocol may later be used for umbrella, vertical, country, and local registry scopes.

**Client**: The customer's app or web browser that searches nodes via a registry and communicates directly with the selected node.

## 3. Design Principles

1. **Direct communication**: After discovery, the customer talks directly to the restaurant. The registry is out of the loop.
2. **Restaurant-owned data**: Menu, orders, and customer contact stay with the restaurant.
3. **Endpoint-agnostic**: The protocol does not lock restaurants to one hosting pattern. The restaurant chooses its own endpoint.
4. **Failover by default**: Clients have a list of backup registries and automatically try the next one if the primary is down.
5. **Deliberately minimal**: v0.1 contains only what is needed to prove the concept.
6. **Anti-capture core**: Core discovery and direct ordering must remain implementable without commercial permission or dependence on a single platform.
7. **Explicit order consent**: A node can be discoverable without accepting orders. Clients must only offer ordering when the node explicitly announces an order mode that allows it.
8. **Node-owned identity**: A node may sign its announcements and heartbeats so registries can reject unauthorized or stale updates to an existing `node_id`.
9. **Identity transparency without central ownership**: Registries may record public signed node identity history, but they must not hold node private keys or become the authority that owns all node identities.
10. **Scoped registries, not scoped identities**: Registries may exist at umbrella, vertical, country, or local scope, but scope must not replace node-owned identity.

## 3.1 Market Position

P4P is not anti-business.

It is anti-rent on first contact.

The point is not to ban companies like Wolt from participating.

The point is to make sure no company has to own the basic connection between restaurant and customer.

If a large actor wants to build on top of P4P, that is acceptable.

But they should compete as a module, service, or interface layer, not as the gatekeeper to discovery itself.

That means:
- core discovery and direct ordering should remain open
- registries may be operated by anyone
- modules may be commercial or free
- no commercial module should be required for basic interoperability
- dominant actors should be able to participate without controlling the protocol

## 4. Data Model

### 4.1 Node Object

```json
{
  "node_id": "dk-brondby-test-001",
  "name": "P4P Test Pizzeria",
  "location": {"lat": 55.6517, "lng": 12.4126},
  "country": "DK",
  "city": "Brondby",
  "categories": ["pizza", "kebab"],
  "endpoint": "https://test-pizzeria.example.com/p4p",
  "open": true,
  "order_mode": "test",
  "modules": [],
  "node_public_key": "ed25519:example-public-key",
  "delegation": {
    "root_public_key": "ed25519:example-root-public-key",
    "issued_at": "2026-04-30T17:00:00Z",
    "expires_at": "2026-05-30T17:00:00Z",
    "role": "primary",
    "capabilities": ["announce", "heartbeat"],
    "signature": "ed25519:example-root-signature"
  },
  "signed_at": "2026-04-30T18:00:00Z",
  "signature": "ed25519:example-signature",
  "protocol_version": "0.1"
}
```

| Field | Description |
|---|---|
| `node_id` | Stable self-assigned unique identifier. Must use lowercase ASCII slug form: `^[a-z]{2}-[a-z0-9]+(?:-[a-z0-9]+)*-\\d{3,}$`. The first segment is the lowercase country code. The final segment is a numeric suffix. Once announced, it should stay stable for that node. |
| `name` | Display name. |
| `location` | WGS84 coordinates. |
| `country` | ISO 3166-1 alpha-2 country code. |
| `city` | City name, free format. |
| `categories` | Lowercase canonical tokens matched by exact equality in discovery, for example `pizza`, `kebab`, `burger`, `sushi`. Recommended token pattern: `^[a-z0-9][a-z0-9-]*$`. |
| `endpoint` | HTTPS URL to the node's own API for v0.1. Loopback HTTP on `127.0.0.1` or `localhost` is allowed only for local reference development. |
| `open` | Whether the node is currently open/discoverable. This is separate from order consent. |
| `order_mode` | Whether the node accepts orders: `disabled`, `menu_only`, `test`, or `live`. If omitted, clients and registries must treat it as `disabled`. |
| `modules` | List of supported modules. Empty in v0.1. |
| `node_public_key` | Optional Ed25519 public key for signed node announcements. |
| `delegation` | Optional root-signed delegation for the announced node key. Used when a root restaurant identity delegates announce/heartbeat rights to an operational node key. |
| `signed_at` | Optional timestamp for the signed announcement. |
| `signature` | Optional Ed25519 signature over the node object without the `signature` field. |
| `protocol_version` | P4P protocol version. |

If `delegation` is present, it carries:

- `root_public_key`
- `issued_at`
- optional `expires_at`
- `role`: `primary` or `backup`
- `capabilities`: in the current skeleton, `announce` and/or `heartbeat`
- `signature`: a root-key signature over the delegation payload

In this model:

- the operational node key still signs the full node announcement
- the root key signs the delegation that authorizes that operational key for that `node_id`
- registries verify both signatures when delegation is present

Root-managed nodes may also publish a separate root-signed node manifest to registries.

That manifest is a lifecycle document, not a discoverability payload.

Current manifest fields:

- `node_id`
- `root_public_key`
- `manifest_version`
- `issued_at`
- `keys`: one or more operational key entries with `node_public_key`, `role`, `capabilities`, `status`, and optional `expires_at`
- `signature`

If the root key itself changes for an existing root-managed `node_id`, the new manifest must be accompanied by a previous-root rotation proof containing:

- `node_id`
- `previous_root_public_key`
- `next_root_public_key`
- `rotated_at`
- `signature`

### 4.2 Registry-Added Fields

`last_seen` is set by the registry, never by the node. It is updated on every heartbeat.

`distance_km` is calculated on discovery queries.

A node is discoverable as open only when:
- `open = true`
- `last_seen` is no older than 180 seconds

Discovery does not imply permission to receive orders.

`order_mode` defines order consent:

| Mode | Meaning |
|---|---|
| `disabled` | The node does not accept orders. Clients must not show an active order action. |
| `menu_only` | The node is intentionally discoverable for menu/status only. Clients may show menu but must not send orders. |
| `test` | The node accepts test orders only. Clients must make that visible. |
| `live` | The node operator has enabled real order intake. |

The registry stores and returns the announced `order_mode`.

The registry does not verify that a restaurant has approved live orders.

Live order verification belongs in the node operator, trust, and certification layers.

### 4.3 Menu Format

```json
{
  "currency": "DKK",
  "updated_at": "2026-04-30T15:00:00Z",
  "items": [
    {
      "id": "margherita",
      "name": "Margherita",
      "description": "Tomat, mozzarella, oregano",
      "price": 75,
      "category": "pizza"
    }
  ]
}
```

Price is an integer in whole DKK for v0.1.

### 4.4 Order Format

```json
{
  "customer_name": "Anna Hansen",
  "customer_contact": "+4512345678",
  "fulfillment": "pickup",
  "items": [
    {"id": "margherita", "quantity": 2}
  ],
  "note": "No onions",
  "client_version": "p4p-web-0.1"
}
```

`fulfillment` supports `pickup` in the v0.1 reference implementation. The field remains extensible for later delivery flows.

### 4.5 Order Response

Accepted:

```json
{
  "accepted": true,
  "order_id": "test-2026-04-30-001",
  "estimated_ready": "2026-04-30T18:25:00Z",
  "message": "Bestilling modtaget. Klar til afhentning om 20 minutter."
}
```

Rejected:

```json
{
  "accepted": false,
  "reason": "closed",
  "message": "Vi lukker om 5 minutter."
}
```

## 5. Endpoints

### 5.1 Registry

**`POST /announce`**: Node registers itself or updates metadata. Body: Node object. Response: `{"status": "ok", "node_id": "..."}`

If a node includes `node_public_key`, `signed_at`, and `signature`, the registry verifies the signature before storing the announcement.

When a registry already has a signed announcement for a `node_id`, later announcements for that `node_id` must be signed by the same public key.

For a signed `node_id`, `signed_at` must be an RFC 3339 timestamp with timezone and must be strictly newer than the last accepted signed event for that `node_id` at that registry.

If a node also includes `delegation`, the registry verifies a second signature:

1. the operational node key signs the full node announcement
2. the root key signs the delegation that binds `node_id` + operational `node_public_key` + role + capabilities

In the current skeleton, a delegated announcement may authorize:

- `announce`
- `heartbeat`

If a registry also has a current node manifest for that `node_id`, the delegated announcement must match an active manifest entry for that operational key.

That means:

- the announcement delegation must point to the same `root_public_key` as the current manifest
- the announced operational key must appear in the current manifest
- the manifest entry must still be `active`
- the manifest entry must still allow the required capability

If a registry has no node manifest yet, later delegated announcements for the same `node_id` must still continue to use the same `root_public_key`.

**`POST /node-manifest`**: Root-owned lifecycle update endpoint. Body: `{"manifest": {...}, "root_rotation": {...}}`, where `root_rotation` is optional and only used when the root key changes.

The registry verifies:

1. the manifest signature with `manifest.root_public_key`
2. monotonic `manifest_version`
3. strictly newer `manifest.issued_at`
4. if the root key changes, a valid previous-root rotation proof signed by the currently known root key

The current node manifest is then used to:

- reject later announces from revoked or expired operational keys
- reject heartbeats from revoked or expired operational keys
- hide revoked or expired operational keys from discovery results immediately

Future direction: a registry may record each verified signed announcement as a node identity event and later publish a registry-signed log or snapshot.

The intended verification chain is:

1. node signs announcement
2. registry verifies node signature
3. registry records identity event
4. registry signs log or snapshot later
5. client verifies both node signature and registry log signature

This is a transparency layer. It is not restaurant certification.

**`GET /identity-log`**: Reference inspection endpoint for signed node identity history. Returns public identity records and append-only signed-announcement events. It must not return node private keys.

This endpoint is informational in the current reference implementation.

**`GET /registry-source`**: Reference snapshot endpoint for later mirroring and umbrella ingestion. Returns the registry's current stored nodes, current node manifests, public identity records, public identity events, and the registry's declared `registry_metadata`. This is a source export, not a client discovery surface.

The default reference runtime declares `export_scope: "local_only"`. That means mirrored cache is not re-exported as fresh source-of-record state.

The first umbrella-ingest extension also allows `export_scope: "local_plus_trusted_mirrors"`. In that mode the registry still exports its own local state as canonical top-level source, but it may also attach `mirrored_sources` as preserved nested upstream snapshots.

If the registry has its own signing key configured, the snapshot may also include `registry_public_key` and a registry signature over the full snapshot payload.

`registry_metadata` should be able to describe:

- `registry_type`: `umbrella`, `vertical`, `country`, or `local`
- `capabilities`: `can_onboard_nodes`, `can_relay_sources`, `can_curate_active_index`, `can_moderate_directory`, `can_issue_trust_claims`, `can_reexport_sources`
- `scope`: `vertical_id`, `country_code`, `locality_id`
- `delegated_by_registry_url` when the registry operates under a broader delegated umbrella

**`POST /registry-source/import`**: Reference mirror-ingest endpoint. Accepts a `GET /registry-source` snapshot from another registry, verifies the optional registry signature, and caches it as raw mirrored source state.

For public registry URLs, a mirrored snapshot must carry a valid registry signature. Unsigned source import is allowed only for loopback HTTP local reference development.

Imported mirrored records are evidence, not endorsement. They land in raw mirror cache first and must not become discoverable merely because they were imported.

The current reference runtime promotes mirrored state into a separate curated active index only through explicit policy. `GET /discover` reads local canonical nodes plus the curated active index. It must not read directly from raw mirror cache.

Promotion must preserve provenance metadata such as:

- original `source_registry_url`
- `source_relay_registry_url` when the snapshot arrived through a relay
- `source_kind`
- `source_discovery_basis`
- `source_snapshot_hash`
- `source_exported_at`
- `source_imported_at`
- `source_last_synced_at`
- `source_freshness_state`

Stale or revoked upstream records must be de-promoted from the curated active index during sync/import, and read-time safety may enforce the same rule again.

The reference runtime also persists a curated promotion decision record per mirrored source. That record is not the source of truth for node identity. It is an explanation layer between raw evidence and curated discoverability: why a source was promoted or denied, whether the source is still active, and which node ids are currently exposed through the curated active index.

The reference runtime may also persist a manual curated override per mirrored source. Overrides are visibility controls, not identity edits. They may allow or deny discoverability among still-valid mirrored evidence, but they must not revive stale, revoked, unsigned, or otherwise invalid upstream records.

The reference runtime may also persist directory-level claims per `node_id`. That layer sits above `GET /discover`, not inside it. Directory claims may annotate or hide otherwise discoverable nodes in a separate public directory without rewriting source evidence, curated promotion decisions, or curated overrides.

The reference runtime may also persist signed trust claims as a separate transportable annotation layer above the moderated directory. Trust claims may be issued by one registry, imported by another, and projected into `GET /directory`, but they must not change node identity, raw source evidence, or `GET /discover`.

Nested `mirrored_sources` are deliberately stricter than ordinary mirrored discovery:

- only `trusted_upstream` mirrored sources may be re-exported
- each nested snapshot must keep `export_scope: "local_only"`
- nested snapshots must preserve the original upstream `registry_url` and registry signature
- re-export must declare the relay registry separately instead of flattening the upstream into new local source-of-record data

**`GET /registry-mirrors`**: Reference inspection endpoint that returns currently cached mirrored registry sources, whether they are still active, whether they are currently eligible for discovery, and whether they were imported directly or relayed by another registry.

**`GET /curated-promotions`**: Reference inspection endpoint that returns the persisted promotion decision record for each mirrored source. This surface explains why a source is promoted or denied for the curated active index, not whether that source owns identity.

**`GET /curated-overrides`**: Reference inspection endpoint that returns persisted manual allow/deny overrides for mirrored sources.

**`POST /curated-overrides`**: Reference control endpoint that stores a manual allow/deny override for one mirrored source. This endpoint is only valid for registries whose metadata declares `can_curate_active_index: true`. An override may steer curated visibility only when the underlying mirrored evidence is still active and valid.

**`GET /directory`**: Reference moderated public directory endpoint. Query parameters match `GET /discover`. The runtime starts from discoverable nodes and then applies directory-level claims such as `reviewed`, `verified`, `hidden`, `spam`, or `local_only`.

This surface is intentionally separate from `GET /discover`.

`GET /discover` remains the operational discoverability view.

`GET /directory` may be narrower and more curated.

**`GET /directory-claims`**: Reference inspection endpoint that returns persisted directory-level claims per `node_id`.

**`POST /directory-claims`**: Reference control endpoint that stores directory-level claims per `node_id`. This endpoint is only valid for registries whose metadata declares `can_moderate_directory: true`.

**`GET /trust-claims`**: Reference inspection endpoint that returns signed trust claims currently stored by this registry.

**`POST /trust-claims`**: Reference control endpoint that issues a signed trust claim for one `node_id`. This endpoint is only valid for registries whose metadata declares `can_issue_trust_claims: true`, and it requires a configured registry signing key.

**`POST /trust-claims/import`**: Reference control endpoint that imports a signed trust claim issued by another registry. This endpoint is only valid for registries whose metadata declares `can_moderate_directory: true`.

**`POST /registry-sync`**: Reference runtime endpoint that fetches `GET /registry-source` from configured upstream registries and imports the results into the local mirror cache.

**`GET /registry-sync`**: Reference runtime endpoint that returns configured upstream registries, effective trusted upstream registries, mirror discovery policy, sync interval, mirror TTL, and the last sync results.

**`GET /discover`**: Client finds open nodes. Query: `lat`, `lng`, `radius` (km, default 5), `category`, `country`. Response: `{"nodes": [...], "registry_version": "0.1", "query_time": "..."}`.

Each discoverable node view also carries provenance:

- `source_kind`: `local` or `mirrored`
- `source_registry_url`: set when the result comes from mirrored upstream state
- `source_relay_registry_url`: set when the importing registry is relaying an upstream source rather than serving it as the original source
- `source_signature_verified`: optional mirror-trust hint showing whether the imported upstream source snapshot carried a verified registry signature
- `source_discovery_basis`: `local_registry`, `manual_override_allow`, `trusted_upstream`, `trusted_relayed_upstream`, or `all_active_policy`
- `source_snapshot_hash`, `source_exported_at`, `source_imported_at`, `source_last_synced_at`, `source_freshness_state`: provenance and freshness hints for the currently exposed mirrored evidence

The separate moderated directory surface may also attach:

- `directory_claims`
- `directory_reason`
- `directory_set_by`
- `directory_expires_at`
- `directory_set_at`
- `trust_claims`
- `trust_claim_issuers`

**`POST /heartbeat`**: Node confirms that it is alive. Body: `{"node_id": "...", "open": true}`. Sent every 60 seconds.

Signed nodes must also sign heartbeat updates using the same node key.

For signed nodes, heartbeat `signed_at` must also be strictly newer than the last accepted signed event for that `node_id` at that registry.

If the stored node announcement carries delegation, the registry must also enforce that:

- the delegation is still active
- `heartbeat` is included in delegation capabilities

If the registry also has a current node manifest for that `node_id`, the stored operational key must still match an active manifest entry that allows `heartbeat`.

**`GET /registry-info`**: Returns info about this registry and known backup registries. In `v0.1`, this data is advisory. Clients should merge it with their locally configured seed registries and must not discard pinned seed registries based only on unsigned `/registry-info` data.

### 5.2 Node

**`GET {endpoint}/menu`**: Returns menu in format 4.3.

**`POST {endpoint}/order`**: Accepts order in format 4.4 only when `order_mode` is `test` or `live`. Returns response in format 4.5. Nodes with `order_mode` set to `disabled` or `menu_only` must reject the order.

**`GET {endpoint}/info`** (optional): Opening hours, payment methods, delivery details. Free format in v0.1.

## 6. Tier System and Failover

Clients start with a small hardcoded seed list of registries in priority order:

```json
[
  {"tier": 0, "url": "https://registry.p4p.example"},
  {"tier": 1, "url": "https://backup1.p4p.example"},
  {"tier": 2, "url": "https://community.example.com/p4p"}
]
```

Clients try tier 0 first. On timeout (5 seconds) or error, they try the next tier.

The list may be extended via `/registry-info` after a successful request, but `v0.1` clients should merge that advisory data with their local seed list rather than replacing pinned seeds outright.

In `v0.1`, this failover model assumes the node is present in both registries, typically by dual announce and dual heartbeat from the node itself.

Registry synchronization in `v0.1` is manual and optional.

There is no automatic registry-to-registry state sync in this version.

Automatic sync is deferred to `v0.2`.

## 6.1 Future Registry Scope Model

The same registry protocol may later be used at several scopes.

Examples:

- umbrella registry
- vertical registry
- country registry
- local or community registry

Illustrative direction:

`Protocols4People -> Pizza4People -> Denmark -> local city or region registries`

A backup registry is different from a sub registry.

A backup registry is redundancy for the same scope.

A sub registry is a narrower discovery surface inside a broader registry family.

The same node may appear in more than one scope at the same time.

For example, one pizza node may appear in:

- an umbrella registry
- a pizza vertical registry
- a Denmark registry
- a local city registry

This makes the long-term network closer to a scoped federation graph than to one permanent rooted directory.

The important rule is:

registry scope does not create or replace node identity.

Canonical node identity still comes from:

- node keys
- root keys
- delegations
- node manifests

Scoped registries may:

- accept direct node announces
- ingest signed snapshots or event feeds from other registries later
- filter or curate what they show

They must not become second identity authorities for the same node.

## 6.2 Future Umbrella And Master Directory Model

A future umbrella or master registry should not collapse everything into one flat master list.

It should keep at least three separate layers:

1. raw identity history
2. current active index
3. moderated trust directory

### Raw identity history

This is the append-only source layer.

It should preserve the fact that a node was announced, even if later state changes make it inactive, revoked, rotated, hidden, or spam-flagged in other layers.

### Current active index

This is the operational discovery view.

It is derived from current valid state such as:

- latest accepted announcement
- current heartbeat
- current node manifest
- current registry scope

This is the layer ordinary discovery clients should search.

### Moderated trust directory

This is the organization or community layer on top.

It may add claims or flags such as:

- reviewed
- verified
- hidden
- spam
- local-only

That layer may remove a node from a public directory view without erasing underlying signed history.

For example, an umbrella organization such as `Protocols4People` may carry broad history while still publishing a narrower moderated public directory.

This separation is a future federation rule.

The current `v0.1` reference runtime now includes the first moderated-directory skeleton on top of `GET /discover`, but not yet broader cross-registry trust lists or certification flows.

## 7. Module System

Core is discovery, menu, and order. Everything else is a module.

In `v0.1`, the base case keeps `modules` empty.

That means `modules: []` is valid and expected, but `v0.1` nodes may also announce opaque module ids.

The field is reserved for the next layer. It is not an active `v0.1` module execution contract.

If a `v0.1` node includes module ids, they are opaque strings only.

Example:

```json
["p4p.payment.cash"]
```

Clients may display these ids.

They must not treat them as certified, trusted, or executable module declarations.

Menu is not a module in P4P. The public menu endpoint is core. A future menu importer may be a module, but the menu endpoint itself is part of the base protocol.

For `v0.2`, a node should be able to declare which modules it supports.

A node-level module declaration should say:
- which module is active
- which provider supplies it, if any
- which version is active
- whether it is public, operator-only, or trust-only
- whether it is active, fallback-only, or disabled for this node
- what the customer or client minimally needs to know about capability and data access

Illustrative `v0.2` direction:

```json
{
  "module_id": "p4p.payment.mobilepay",
  "provider_id": "dk.mobilepay",
  "version": "0.1",
  "status": "active",
  "visibility": "public",
  "readiness": "test",
  "capabilities": ["authorize_payment"],
  "data_access": ["customer_phone", "order_total"],
  "customer_notice": "Customer pays through MobilePay."
}
```

The full module manifest stays a separate document.

The node declaration is the smaller public per-node activation view.

This is still not a `v0.1` schema change.

The likely transition is:

- `modules: ["..."]` remains the coarse compatibility field
- a later `module_declarations: [...]` field carries the richer per-node shape
- clients may prefer `module_declarations` when present

Breaking changes are allowed before `v1.0`, so the exact module declaration shape may be introduced in `v0.2`.

Examples of future module categories:
- Payments (`MobilePay`, `Stripe`, cash)
- Delivery (own couriers, third-party couriers, pickup)
- Reviews (multiple review systems can exist)
- Identity (Solid pods, WebID, anonymous)
- Loyalty, inventory, accounting integration
- POS, kitchen printer, and receipt integrations
- CVR verification and trust-list services
- Hosted backup-node services

Any party can publish a module. Restaurants choose what they support. Customers choose what they trust.

P4P builds the socket. Others build the appliances.

Modules may be:
- open and free
- commercial and paid
- community-maintained
- company-operated

The protocol should allow all of them, while keeping the core usable without any proprietary dependency.

### Module Providers

A module provider is any person, company, community, or public body that publishes a P4P-compatible module.

Examples:
- a payment company publishing a payment module
- a delivery company publishing a delivery module
- a POS vendor publishing an integration module
- a municipality or trust group publishing a CVR verification module
- a hosting provider selling backup-node hosting

Providers can sell useful functions.

They must not own discovery.

A provider manifest should eventually identify:
- provider id
- legal or public name
- website
- public signing key
- supported modules
- contact or reporting channel

A module manifest should eventually identify:
- module id
- module type
- provider id
- version
- required node configuration
- data required from the node or customer
- API or flow contract
- signature

Modules must declare data access before use.

For example, a payment module may need `order_total` and a merchant id. A delivery module may need a delivery address. A printer module may need the order contents. This should be explicit so a node operator and client can understand what leaves the core flow.

### Module Governance and Trust

Open wiki in Git with listed modules.

Trusted lists curated by trust groups are planned for later. Clients should be able to show trusted modules by default while still allowing broader discovery through filters.

Certification should be claim-based, not permission-based.

That means:
- a node can sign its own node manifest
- a module provider can sign its own module manifest
- a trust list can claim that a provider, module, or node has been reviewed
- a CVR verification service can claim that a node belongs to a real company
- clients choose which trust lists they accept

The registry may list what a node announces.

The registry must not become the authority that decides which restaurants or modules are certified.

## 8. Privacy

The registry does not need to see:
- orders
- basket contents
- payment
- customer identity
- delivery address

The registry does see:
- public node metadata
- client search coordinates
- which nodes are returned

Privacy is a consequence of the architecture, not a guarantee. Clients that want rougher location privacy may round GPS coordinates before query.

## 9. Security

v0.1 is **not production-secure**.

The reference implementation now includes a narrow node-identity skeleton:

- Ed25519 signed announcements
- registry protection against unsigned, tampered, or older signed updates to an existing signed `node_id`
- signed heartbeats for signed nodes
- read-only identity-log inspection for signed announcements

This proves control of a node key.

It does not prove restaurant identity, CVR binding, module trust, or production abuse resistance.

The current reference implementation also includes the first delegated operational-key skeleton:

- a root key may sign a delegation for one operational node key
- that delegation binds `node_id`, role, and capabilities
- registries verify the root delegation when it is present
- a root-signed node manifest may revoke operational keys or move a `node_id` to a new root key through a previous-root rotation proof
- delegated backup nodes are represented only as a role in this skeleton, not yet as a full sync/runtime protocol

No central P4P server should hold all node private keys.

A server only has private keys for nodes it actually hosts.

Registries should store public signed announcements and, later, public identity-log events.

They should not store node private keys.

Backup registries do not need node private keys.

Hosted backup nodes should eventually use delegated operational keys, not the restaurant's root node key.

Local and development nodes may sign announcements, but their identities should not automatically enter a public identity log.

Remaining limitations:

- Real-world restaurant ownership is not authenticated
- unsigned legacy nodes can still exist during early development
- Registry does not certify restaurants, modules, or providers
- Public registry-signed identity logs are not implemented yet
- Root rotation is narrow and manual. There is no lost-root recovery flow.
- Multi-node restaurant manifests and backup-node sync are not implemented yet
- Public-facing client-to-node communication requires HTTPS. Loopback HTTP is allowed only for local reference development.

This is deliberate. Security layers such as provider manifests, broader trust lists, CVR binding, broader recovery flows, multi-node manifest governance, or web-of-trust are deferred to later versions.

Do not deploy v0.1 to production without adding your own security.

## 10. Not in v0.1

- Payment
- Delivery
- User accounts
- Reviews and ratings
- Pre-orders
- Module implementations
- Module provider manifests
- Lost-root recovery
- Multi-node restaurant manifest governance
- Production node identity lifecycle
- Broader trust lists and certification
- Automatic registry synchronization
- Protection against fake nodes
- Multi-language
- Discovery pagination

v0.1 assumes fewer than 100 nodes per query.

## 11. Version Roadmap

| Version | Status | Content |
|---|---|---|
| v0.1 | Alpha (April 2026) | Discovery + direct order |
| v0.2 | Planned | Module declarations, module providers, node identity, broader trust lists, registry sync |
| v1.0 | Goal | First stable release. Production-ready. |

Breaking changes are allowed through v0.x. From v1.0 onward: semver.

## 12. Reference Implementation

`github.com/[handle]/p4p`:

- `registry/main.py`: FastAPI server, default in-memory storage with optional SQLite-backed snapshot persistence
- `demo-node/demo_node.py`: Simulated restaurant
- `client/index.html`: Web client with geolocation
- `SPEC.md`: This specification
- `README.md`: Quickstart

`lab/` is a separate local operator and debug harness for the reference implementation.

It is not part of the protocol surface and defines no required protocol APIs.

For the reference node runtime, `P4P_REGISTRY_URLS` is the canonical configuration input for failover:

- comma-separated full registry base URLs
- dual announce and dual heartbeat across that list
- `P4P_REGISTRY_URL` retained only as a backward-compatible single-registry fallback

## 13. Definition of Done for v0.1

Implementation is complete when this sequence can be shown on video:

1. Registry server starts
2. Demo node announces itself
3. Client finds demo node via `/discover` based on GPS
4. Client fetches menu from the demo node's own `/menu` endpoint
5. Client sends order to the demo node's own `/order` endpoint
6. Demo node prints the order in the terminal
7. Tier 0 registry is shut down and the client automatically switches to tier 1

When that video exists, v0.1 is launched.

## 14. Launch Context

April 30, 2026: Just Eat exits Denmark. Their customers are redirected toward Uber Eats through a marketing arrangement.

Wolt -> DoorDash -> SoftBank
Just Eat -> Prosus -> Naspers
Uber Eats -> Uber

P4P is an open Danish proposal for a different direction.

## 15. Contributions and Governance

v0.1 is maintained by Hedegreen Research. Issues and pull requests are welcome on GitHub.

From v0.2 onward, an open trust group can be established to evaluate protocol changes and module approvals.

---

P4P is a phone book for restaurants, not a marketplace for middlemen.

The socket, not the appliances.
