# P4P Module Rules

These rules define what a P4P module is allowed to be.

They are stricter than the current code.

The code can be small. The boundary must be clear.

## 1. Core Is Not A Module

The following are core P4P:
- registry announce
- registry heartbeat
- registry discover
- registry failover metadata
- node menu endpoint
- node order endpoint
- node order mode / order-consent state
- direct client-to-node menu and order flow

Do not turn these into modules.

Especially:

Menu is core.

A menu importer can be a module. The node's public menu endpoint is not.

Order consent is core.

A future verification provider may help prove restaurant identity, but the node's own `order_mode` is not a module.

## 2. Modules Are Add-ons

A module adds an optional capability.

Good module examples:
- payment method
- delivery method
- POS or printer integration
- accounting export
- loyalty
- review provider
- CVR verification
- trust list
- hosted backup-node service

If removing a module breaks discovery or direct ordering, the module is too deep.

## 3. Registry Is Not The Gatekeeper

The registry may list module ids announced by a node.

The registry must not decide:
- which module providers are allowed
- which restaurants are certified
- which modules are trusted
- which clients may use the protocol

Trust belongs in signatures, manifests, and client-selected trust lists.

## 4. Modules Must Declare Data Access

Every module must say what data it needs.

Examples:
- payment: order total, merchant id, optional customer contact
- delivery: address, phone number, ready time
- printer: order lines and note
- accounting: completed order totals and VAT data

If a module cannot explain its data needs, it is not ready.

## 5. Node Operator Controls Modules

The node operator layer decides which modules are active for one restaurant node.

It may store:
- module settings
- provider credentials
- merchant ids
- printer settings
- signing keys

The node operator layer is not itself a module.

It is the restaurant-owned control surface.

## 6. v0.1 Module Handling

In `v0.1`, `modules` is an array of opaque string ids.

Examples:

```json
["p4p.payment.cash"]
```

That does not mean the module has been executed, certified, or trusted.

It only means the node announced support for that capability.

The full module declaration object belongs in `v0.2`.

## 7. First Module Rule

The first module should be deliberately boring.

`p4p.payment.cash` is a good first module because:
- it needs no third-party API
- it does not touch discovery
- it does not require payment processing
- it shows module/provider/data-access structure
- a restaurant can understand it
