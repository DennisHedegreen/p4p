# P4P Reference Modules

This folder contains reference manifests and internal test modules for the planned P4P module model.

It is not a production module marketplace.

It is not a certification list.

It is not a claim that every listed module is live, trusted, or customer-facing.

For the public community-module guide, read:

- `../docs/modules/README.md`
- `../docs/COMMUNITY-MODULES.md`
- `../docs/MODULE-RULES.md`
- `../docs/MODULE-PROVIDERS.md`
- `../docs/MODULE-EXECUTION-CONTRACT.md`

## Current Reading

The current module manifests show how P4P expects optional capabilities to declare:

- provider identity
- module id
- lane
- visibility
- capabilities
- input and output events
- permissions
- blocking policy
- data access
- readiness
- operator status

In active `v0.1` node announcements, module ids are still opaque strings.

The richer manifest shape is the planned module/provider direction.

## Status Families

Public readers should treat module status as a label, not as certification.

- `reference` or `reference-example`: P4P reference material
- `internal-mock`: internal debug/test module
- `community`: third-party/community material
- `experimental`: early module work
- `operator-local`: local restaurant or node-operator module
- `planned`: manifest or design material that is not executable yet

## Payment Boundary

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant/operator.

`p4p.payment.cash` is a reference adapter for payment outside the protocol.

`p4p.payment.godpay-mock` and `p4p.payment.chaospay-mock` are internal mock/test modules only.

## Operator Surface Boundary

`p4p.catalog.editor` is a reference operator-surface module for maintaining
the structured item catalog that every customer menu surface should read from.

It is not a customer menu layout. It is the restaurant-side source of truth for
item ids, names, descriptions, categories, prices, and active/inactive
availability.

`p4p.kitchen.screen` is a reference operator-surface module for the pilot node.

It is not a public customer feature. It gives the restaurant operator a local
order queue for accepting, rejecting, marking ready, completing, or cancelling
orders through token-protected operator endpoints.

## Customer Surface Boundary

`p4p.menu.list` is a reference public customer menu surface for the pilot node.

It reads active items from the structured catalog and lets the customer build a
normal P4P order request. It does not own item ids, prices, inventory, payment,
or operator state.

`p4p.menu.photo-map` is a reference public customer menu surface for the pilot
node.

It presents active catalog items as clickable regions in a paper-menu style
layout. It is a presentation module, not OCR, not the catalog source of truth,
and not a payment or inventory owner.

`p4p.customer.status` is a reference public read-only status module for the
pilot node.

It lets a customer check whether their submitted order is accepted, ready,
completed, cancelled, or rejected. It must not expose customer contact details,
customer name, order notes, operator-only events, or internal restaurant data.
