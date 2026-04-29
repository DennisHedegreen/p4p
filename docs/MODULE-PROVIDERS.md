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

Design target:

```json
{
  "provider_id": "dk.example-pay",
  "name": "Example Pay",
  "website": "https://example-pay.test",
  "public_key": "ed25519:...",
  "contact": "security@example-pay.test",
  "modules": ["p4p.payment.example-pay"]
}
```

This manifest should be signed by the provider.

It lets clients, nodes, and trust lists reason about who is behind a module without making the registry a certification authority.

## Module Manifest

A module manifest should describe the capability itself.

Design target:

```json
{
  "module_id": "p4p.payment.example-pay",
  "type": "payment",
  "provider_id": "dk.example-pay",
  "version": "0.1",
  "requires": ["order_total", "customer_phone", "merchant_id"],
  "data_access": ["order_total", "customer_contact"],
  "entrypoint": "https://example-pay.test/p4p/payment",
  "signature": "..."
}
```

The exact schema belongs in `v0.2`.

For now, the important rule is that modules must declare what they need before a node enables them.

## Node Declarations

A node operator chooses which modules are active for a specific restaurant node.

The node can then announce active modules in its public node metadata.

Illustrative direction:

```json
{
  "id": "p4p.payment.example-pay",
  "version": "0.1",
  "status": "active",
  "provider_id": "dk.example-pay"
}
```

This declaration says the node supports the module.

It does not mean the registry has certified it.

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

