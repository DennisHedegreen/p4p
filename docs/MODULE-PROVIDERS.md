# P4P Module Providers

This document describes the planned `v0.2` module-provider model.

It is not an active `v0.1` contract.

`v0.1` proves discovery, direct menu/order, and registry failover. `v0.2` should make it possible for nodes to declare optional capabilities without giving control of the core protocol to a platform.

## Core Rule

Module providers can sell or publish functions.

They must not own discovery.

The core P4P loop must remain usable without any module:

`Client -> Registry -> Node` for discovery.

`Client -> Node` for menu and order.

If removing a module breaks basic discovery or direct ordering, that module is too deep.

## What A Module Provider Is

A module provider is any actor that publishes a P4P-compatible capability.

Examples:
- payment provider
- delivery provider
- POS or kitchen-printer vendor
- menu-import tool
- accounting or invoice integration
- CVR verification service
- trust-list maintainer
- hosted backup-node provider

The provider may be commercial, open source, community-operated, public-sector, or restaurant-owned.

## Provider Manifest

A provider manifest should identify who publishes the module.

The first concrete draft now lives in:

- `docs/schemas/provider-manifest.schema.json`
- `docs/examples/provider-manifest.json`
- `modules/*/provider.json` as reference manifests

Current frozen draft shape:

```json
{
  "provider_id": "dk.example-pay",
  "name": "Example Pay",
  "description": "Payment provider for direct restaurant checkout.",
  "website": "https://example-pay.test",
  "public_key": "ed25519:...",
  "contact": "security@example-pay.test",
  "modules": ["p4p.payment.example-pay"],
  "supported_lanes": ["public_capability"],
  "status": "signed-provider",
  "signature": "ed25519:..."
}
```

This manifest should be signed by the provider.

It lets clients, nodes, and trust lists reason about who is behind a module without making the registry a certification authority.

## Module Manifest

A module manifest should describe the capability itself.

The first concrete draft now lives in:

- `docs/schemas/module-manifest.schema.json`
- `docs/examples/module-manifest-print-primary.json`
- `modules/*/module.json` as reference manifests

Current frozen draft shape:

```json
{
  "module_id": "p4p.payment.example-pay",
  "module_class": "payment",
  "lane": "public_capability",
  "type": "payment",
  "provider_id": "dk.example-pay",
  "version": "0.1",
  "status": "signed-provider-module",
  "description": "Direct payment module for a named provider.",
  "visibility": "public",
  "capabilities": ["authorize_payment", "report_payment_state"],
  "input_events": ["PAYMENT_REQUIRED"],
  "output_events": ["PAYMENT_MODE_CHANGED", "PAYMENT_FAILED"],
  "permissions": ["read.order.summary", "write.payment.state"],
  "blocking_policy": "blocking",
  "idempotency_scope": "payment_attempt",
  "requires": ["order_total", "customer_phone", "merchant_id"],
  "data_access": ["order_total", "customer_contact"],
  "entrypoint": "https://example-pay.test/p4p/payment",
  "signature": "ed25519:...",
  "public_catalog": {
    "function": "Authorizes provider-backed payment for one restaurant node.",
    "data_access_summary": "Order total, customer contact, and merchant identifier.",
    "trust_status": "provider-signed manifest",
    "readiness": "test",
    "operator_status": "not enabled"
  }
}
```

The important shift is that the manifest now carries not only provider and data-access information, but also the first execution-contract layer:

- module lane
- visibility
- capabilities
- input events
- output events
- permissions
- blocking policy
- idempotency scope

That is still a `v0.2` draft.

It does not change the active `v0.1` node payload, where nodes still announce opaque module ids only.

## Node Declarations

A node operator chooses which modules are active for a specific restaurant node.

The node can then announce active modules in its public node metadata.

That public declaration should stay smaller than the full module manifest.

The first concrete draft now lives in:

- `docs/schemas/node-module-declaration.schema.json`
- `docs/examples/node-module-declaration.json`

Illustrative direction:

```json
{
  "module_id": "p4p.payment.example-pay",
  "provider_id": "dk.example-pay",
  "version": "0.1",
  "status": "active",
  "visibility": "public",
  "readiness": "test",
  "capabilities": ["authorize_payment"],
  "data_access": ["order_total", "customer_contact"],
  "customer_notice": "Customer pays through Example Pay."
}
```

This declaration says the node supports the module.

It does not mean the registry has certified it.

The node-declaration wire shape should stay smaller than the module manifest itself.

The registry may expose that a node has activated `p4p.payment.cash`.

It does not need to carry the entire provider, permission, and fallback contract inline in node metadata.

The intended reading is:

- provider manifest says who publishes the module
- module manifest says how the module behaves in general
- node module declaration says this specific node has activated the module and what the customer or client should minimally know

The likely `v0.2` transition path is:

- keep `modules: ["..."]` as the coarse list during transition
- add `module_declarations: [...]` for the richer per-node public shape
- let clients prefer `module_declarations` when present

## Data Access Principle

Modules must declare data access.

Examples:
- payment module: order total, merchant id, optional customer phone
- delivery module: delivery address, phone number, ready time
- printer module: order contents and note
- accounting module: completed order totals and VAT fields
- CVR verification module: restaurant identity metadata

The node operator should be able to see what data each module needs before enabling it.

Clients should be able to inspect module declarations and decide what they trust.

## Trust And Certification

Certification should be claim-based, not permission-based.

Good claims:
- this provider signed this module manifest
- this trust list reviewed this provider
- this CVR verifier matched this node to a company
- this node signed its own manifest
- this client trusts this trust list

Bad model:
- the registry decides which modules are real
- one vendor controls which providers may exist
- discovery requires a commercial certification layer

The registry can list what nodes announce.

Trust should come from signatures, provider manifests, node identity, and client-selected trust lists.

## Relationship To Node Operator Layer

The node operator layer is the restaurant's private control surface.

It can enable, disable, and configure modules.

It may store provider credentials, API keys, merchant ids, printer settings, and local operational preferences.

It is not itself a module.

It is the place where modules are controlled.
