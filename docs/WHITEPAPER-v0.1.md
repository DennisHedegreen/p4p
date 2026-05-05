# P4P Working Whitepaper v0.1

Status: working whitepaper for the public prototype.

Date: 2026-05-05

Audience: developers, restaurant operators, module builders, journalists, and reviewers who need the project boundary before reading the raw code.

This is not a production promise.

This is not an investment document.

This is not a payment-provider claim.

It is a technical and architectural explanation of what P4P is trying to prove.

## Abstract

P4P is an open protocol for direct restaurant discovery and ordering, with replaceable modules for payments, printing, delivery, POS, booking, trust, inventory, menu presentation, and other operator-owned workflows.

The core claim is small:

basic restaurant-customer discovery and ordering should not require a marketplace platform to own the first contact.

P4P is a phone book, not a marketplace.

P4P is the socket, not the appliances.

Restaurants and node operators choose their modules. Module providers can publish adapters and tools. Customers and clients can inspect what a node declares. Registries can help discovery without becoming the authority that owns restaurant identity, module certification, payment, or customer relationships.

The current implementation is an advanced prototype. It includes a registry, demo node, pilot node, browser client, module manifests, operator controls, catalog/menu surfaces, internal mock payment modules, identity/signature scaffolding, mirror/import work, moderated directory scaffolding, and local lab tools.

The next practical target is a controlled live pilot, not a broad production rollout.

## 1. Problem

Many restaurant ordering systems collapse discovery, ordering, customer relationship, payment surface, ranking, promotion, fees, and operator tooling into one platform layer.

That can be convenient, but it creates a structural problem:

- restaurants depend on a platform to be found
- customers are routed through an intermediary even for simple direct contact
- restaurant identity and menus become platform-shaped
- alternative tools must integrate into the platform rather than beside it
- local operators lose control over which workflows they use

P4P starts from a narrower question:

Can a restaurant expose a small, direct, machine-readable node that lets customers find it, read its current menu, and send an order request without the discovery layer becoming a marketplace middleman?

If that works, everything else can become modular:

- payment adapter
- printer/POS handoff
- kitchen screen
- delivery adapter
- booking adapter
- stock check
- menu importer
- AI menu assistant
- trust claim
- accounting export

The important part is that those tools should compete as modules and services, not as the gatekeeper to first contact.

## 2. Design Position

P4P has three public design slogans because they capture the boundary:

```text
P4P is a phone book, not a marketplace.
P4P is the socket, not the appliances.
P4P core should stay small.
```

This means:

- discovery is not certification
- module listing is not approval
- payment adapter support is not P4P becoming a payment provider
- customer menu presentation is not catalog truth
- operator tooling belongs with the node/operator, not the registry
- basic interoperability must not require a commercial module

The protocol should make direct contact possible.

It should not force one company to own the restaurant-customer relationship.

## 3. Scope And Maturity

The current P4P status is:

```text
advanced prototype
public protocol proof now
controlled live pilot next
not production-ready
```

Implemented prototype areas include:

- registry announce, heartbeat, discover, and registry-info endpoints
- direct node menu and order endpoints
- browser reference client with registry failover
- signed node announcement and heartbeat scaffolding
- optional root-signed delegation and manifest-based node key lifecycle
- registry source export/import and mirror cache work
- moderated directory and trust-claim scaffolding
- reference module manifests and provider manifests
- pilot-node operator controls
- pilot-node catalog, stock, payment-mode, kitchen, customer-status, list-menu, and photo-map menu lanes
- internal mock payment modules for local debugging
- synthetic fixture packs for safe menu and food-image testing
- local lab scenario runner

Not claimed today:

- production restaurant rollout
- production security
- production payment integration
- delivery network
- customer account platform
- verified community module marketplace
- final federation governance
- complete trust ecosystem

This whitepaper documents the current direction and boundary. It should be read together with `SPEC.md`, `ARCHITECTURE.md`, `PILOT-LIVE.md`, and the files in `docs/`.

## 4. Actors

### Customer

The person or client software looking for a restaurant, reading its menu, and sending an order request directly to the restaurant node.

### Restaurant Or Node Operator

The actor responsible for running or controlling a node. This may be the restaurant itself or a technical operator acting for the restaurant.

The node operator controls:

- order mode
- local catalog
- active modules
- operator credentials
- payment adapter selection
- kitchen/order workflow

### Node

The restaurant-owned or restaurant-controlled endpoint.

The node exposes current public state, menu, and order intake.

The node is where private operational choices belong.

### Registry

A public discovery surface.

The registry records active nodes and lets clients search by location, radius, category, and current state.

The registry is not the owner of the node, restaurant, modules, payment, or customer relationship.

### Client

Any customer-side software that can query registries and then talk directly to a node.

The reference client is only one implementation.

### Module Provider

A person, company, community, public body, or open-source maintainer that publishes a P4P-compatible module.

Provider identity belongs in provider manifests and later signatures, not as hidden registry policy.

### Module

An optional capability around the core.

A module can add a payment adapter, printer connector, stock check, kitchen surface, customer menu presentation, trust claim, notification, delivery handoff, or similar workflow.

If removing the module breaks basic discovery, menu fetch, or direct order submission, the module has been placed too deep.

## 5. Core Protocol

The small core is:

```text
announce
heartbeat
discover
node info
menu
order
order consent / order mode
```

The current reference flow is:

1. A node announces itself to one or more registries.
2. The node sends heartbeats so stale nodes disappear from discovery.
3. A client queries a registry for nearby nodes.
4. The client fetches the selected node's menu directly from the node.
5. The client sends an order request directly to the node.
6. The node decides whether orders are disabled, test-only, or live.
7. Optional modules may participate in local runtime lanes.

The public menu endpoint is core.

A menu importer can be a module.

A menu presentation surface can be a module.

But the node's ability to expose a menu is part of the base protocol.

## 6. Order Mode

Discovery must not be confused with permission to receive real orders.

Nodes expose `order_mode` so clients and registries can distinguish:

- `menu_only`
- `test`
- `live`

This matters because a restaurant may be discoverable before it is ready for real ordering.

The controlled live pilot should only use `live` when the operator has intentionally enabled it and understands what the node will receive.

## 7. Reference Implementation

The repository contains several reference layers:

- `registry/`: FastAPI registry implementation
- `demo-node/`: narrow proof node for public protocol and lab flows
- `pilot-node/`: controlled live-pilot foundation
- `client/`: browser reference client
- `p4p_core/`: shared models, money helpers, module catalog loading, flow contracts, and CORS helpers
- `modules/`: provider and module manifests
- `docs/modules/`: human-readable module pages
- `lab/`: local scenario runner and operator test surface
- `scripts/`: public audit and public-site generation helpers

The pilot node is currently the most important live-directed surface.

It includes:

- token-protected operator endpoints
- catalog editor
- customer menu list
- customer photo-map menu
- customer order status
- kitchen screen
- stock validation
- active payment module selection
- built-in cash adapter
- GodPay mock
- declared ChaosPay mock
- optional external payment module manifest loading

The reference implementation is useful because it makes the architecture inspectable. It is not a production-hosting guarantee.

## 8. Module Model

Modules exist so that P4P does not become one large platform product.

A module should declare:

- module id
- provider id
- status
- lane
- visibility
- capabilities
- permissions
- data access
- input events
- output events
- blocking policy
- failure modes
- required configuration
- readiness

Current status families:

| Family | Meaning |
| --- | --- |
| `reference` | P4P reference module or reference example. |
| `internal-mock` | Internal local/debug module. Not real-world provider behavior. |
| `planned` | Manifest/design material that is not executable yet. |
| `operator-local` | Local node/operator module. |
| `community` | Third-party/community material, not automatically approved by P4P. |

The important rule:

publication on GitHub is not certification.

Community modules are welcome, but they must be clearly labeled.

## 9. Current Reference Modules

Current human-readable module pages live in `docs/modules/`.

Implemented or test-ready reference modules include:

- `p4p.catalog.editor`
- `p4p.customer.status`
- `p4p.kitchen.screen`
- `p4p.menu.list`
- `p4p.menu.photo-map`
- `p4p.payment.cash`
- `p4p.payment.godpay-mock`
- `p4p.stock.basic`

Declared or planned modules include:

- `p4p.notify.email`
- `p4p.order.print`
- `p4p.payment.chaospay-mock`
- `p4p.trust.cvr-basic`

These modules are not a production marketplace.

They are reference material showing how a module should explain itself.

## 10. Payment Boundary

This boundary is central:

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant/operator.

P4P core may:

- build an order
- select the node's active payment module
- send an order-scoped payment request to that module
- receive module result events
- expose operator status for active/configured/reachable modules

P4P core must not:

- hold customer funds
- process payments
- store card, wallet, or bank credentials
- issue a payment instrument
- act as merchant of record
- settle funds
- own refunds, chargebacks, or disputes
- describe a fake test ledger as real money or crypto

Do not call this `P4P Pay`.

If a future module integrates a real provider, that module must say who owns the merchant relationship and which external provider handles payment, confirmation, settlement, refunds, disputes, and compliance.

## 11. Internal Payment Test Modules

Internal payment test modules exist only to test P4P flow behavior.

`p4p.payment.cash` is a reference adapter for payment outside the P4P protocol, such as pay-at-pickup or direct in-person payment.

`p4p.payment.godpay-mock` is an executable random approval/failure debug module. It rolls `1..100`, compares the result to a threshold, and records the roll and outcome.

`p4p.payment.chaospay-mock` is a declared future chaos module for ugly edge cases such as timeouts, duplicate callbacks, invalid signatures, wrong amount, late callbacks, conflicting statuses, and state changes out of order.

`Pizzacoin` is a sandbox ledger for local experiments. It is useful for fake balance, module health, idempotency, and adapter-boundary testing.

None of these are real money, real settlement, real wallets, crypto, redeemable value, or production payment methods.

## 12. Menu, Catalog, And Presentation

P4P separates three ideas that platforms often merge:

- catalog truth
- customer menu presentation
- order request

The catalog is operator-owned local item data:

- item id
- name
- description
- price in integer minor units
- currency
- category
- active/inactive availability
- optional presentation image URL

The customer menu can then be shown in different ways:

- `p4p.menu.list`: classic list view
- `p4p.menu.photo-map`: clickable paper-menu style view
- future AI menu assistant: conversation on top of the structured catalog
- future menu importer/OCR: intake tool feeding operator-reviewed catalog data

Important boundary:

images, prompts, OCR output, and AI suggestions are not catalog truth by themselves.

The restaurant/operator-controlled catalog remains the source used for prices, availability, and order item ids.

## 13. Money And Currency

Menu prices and order totals use integer minor units in the node's menu currency.

Examples:

- `6500` with `DKK` means `65.00 DKK`
- `1299` with `USD` means `12.99 USD`
- `1200` with `JPY` means `1200 JPY`

P4P core does not perform currency conversion.

A real payment adapter should receive the amount and currency from the restaurant/node context and hand that to the selected payment provider.

Internal mocks and sandbox ledgers may use explicit test labels only when clearly marked as non-production.

## 14. Trust, Identity, And Registry Scope

Registries help clients find nodes.

They must not become the owner of restaurant identity.

The current reference implementation includes:

- signed node announcements
- signed heartbeats
- node key history
- optional root-signed delegation
- node manifests for operational key lifecycle
- root-rotation proof shape
- signed trust-claim scaffolding
- moderated directory scaffolding

These layers are important because open discovery needs abuse resistance.

They are not yet a complete trust ecosystem.

Longer term, trust should be layered:

- node keys prove control over a node id
- root keys can delegate operational keys
- registries can record signed state
- trust groups can issue claims
- clients can choose which claims they care about

Discovery should remain separable from certification.

## 15. Federation Direction

P4P should not depend on one permanent global registry.

The long-term model is scoped registries:

- umbrella registry
- vertical registry
- country registry
- local/community registry

For example:

```text
Protocols4People -> Pizza4People -> Denmark -> local city or region registries
```

The same node may appear in more than one scope.

A scoped registry is a discovery surface, not a second identity authority.

The current reference runtime includes early registry source export/import and mirror cache work, but full federation is not finished.

## 16. Community Module Economy

P4P should make room for free, commercial, public, and community modules.

Possible module providers include:

- payment companies
- POS vendors
- delivery companies
- printer vendors
- local open-source maintainers
- municipalities or trust groups
- restaurant chains
- independent developers

The repository should encourage people to build modules, but public documentation must keep labels visible:

- reference
- internal mock
- planned
- community
- operator-local
- experimental

No community module should be treated as approved simply because it exists.

No payment module should imply P4P handles money.

## 17. Non-Goals

P4P v0.1 is not:

- a marketplace
- a delivery platform
- a payment provider
- a wallet
- a crypto project
- a customer account platform
- a merchant-of-record system
- a POS system
- a certified restaurant directory
- a finished trust network
- a production security claim
- a verified module marketplace

Some of those things may exist as independent modules or services later.

They should not become the core.

## 18. Roadmap

Near-term:

1. keep GitHub public profile coherent
2. keep module pages and manifests aligned
3. publish this working whitepaper
4. update the public site to expose module pages and the whitepaper
5. continue pilot-node hardening
6. prepare a controlled live pilot with one real restaurant

Prototype module work:

- improve module operator status
- finish ChaosPay mock for failure-path testing
- explore AI menu assistant over structured catalog data
- explore printer/POS handoff
- explore delivery/driver workflow
- keep payment adapters as boundaries, not P4P payment

Trust/federation work:

- tighten node identity lifecycle
- define trust-claim review policy
- clarify scoped registry behavior
- avoid central certification by default

Public proof work:

- keep `pizza4people.com` aligned with the repo
- publish proof-safe documentation
- show what works without overclaiming production readiness

## 19. Success Criteria

P4P is moving in the right direction if:

- a node can be discovered without a platform owning the relationship
- a client can fetch the menu directly from the node
- a customer can submit an order request directly to the node
- the operator can choose modules
- modules can be replaced without rewriting the core
- payment remains an adapter boundary
- the registry does not certify everything by default
- public documentation says what is real and what is only planned
- tests protect the public claim from drifting into product theater

## 20. Short Public Summary

P4P is an open protocol for direct restaurant discovery and ordering.

The core is small: registry, node, menu, order, and current state.

Everything else should be replaceable modules.

P4P is not a marketplace and not a payment provider.

The current code is an advanced prototype, with a controlled live pilot as the next practical gate.
