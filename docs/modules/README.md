# P4P Module Reference

Status: public GitHub reference for the current P4P module manifests.

This directory explains the modules that currently live under `modules/`.

It is not a production module marketplace.

It is not a certification list.

It is not proof that a module is safe for real restaurant use.

The purpose is narrower: make every current module understandable to a new developer or operator without forcing them to inspect raw JSON first.

## Core Boundary

P4P is an open protocol for direct restaurant discovery and ordering, with replaceable modules for payments, printing, delivery, POS, booking, and other operator-owned workflows.

P4P is the socket, not the appliances.

A module is an optional capability around the core. If removing something breaks basic registry discovery, node menu fetch, or direct order submission, it is too deep to be a module.

## Payment Boundary

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant/operator.

Internal mock modules such as GodPay and ChaosPay are only local/debug modules. They must never be described as real money, real settlement, real wallets, crypto, redeemable value, or production payment systems.

## Status Families

Manifest status strings are labels, not certification.

| Family | Meaning |
| --- | --- |
| `reference` | P4P reference example or reference implementation material. |
| `internal-mock` | Internal test/debug module. Not production and not real-world provider behavior. |
| `planned` | Manifest/design material exists, but the module is not executable in the reference runtime yet. |
| `operator-local` | Local node/operator module, usually outside this repo. |
| `community` | Third-party/community module. Not automatically approved by P4P. |

## Current Modules

| Module | Family | Lane | Visibility | Runtime reading |
| --- | --- | --- | --- | --- |
| [`p4p.catalog.editor`](p4p.catalog.editor.md) | reference | operator | operator-only | Pilot-node operator catalog editor. |
| [`p4p.customer.status`](p4p.customer.status.md) | reference | public capability | public | Pilot-node customer order-status page/API. |
| [`p4p.kitchen.screen`](p4p.kitchen.screen.md) | reference | operator | operator-only | Pilot-node operator order queue and status updater. |
| [`p4p.menu.list`](p4p.menu.list.md) | reference | public capability | public | Pilot-node customer list menu. |
| [`p4p.menu.photo-map`](p4p.menu.photo-map.md) | reference | public capability | public | Pilot-node paper-menu style clickable menu. |
| [`p4p.notify.email`](p4p.notify.email.md) | planned | operator | operator-only | Placeholder notification manifest. |
| [`p4p.order.print`](p4p.order.print.md) | planned | operator | operator-only | Placeholder printer/POS handoff manifest. |
| [`p4p.payment.cash`](p4p.payment.cash.md) | reference | public capability | public | Built-in pay-at-pickup/direct-payment adapter. |
| [`p4p.payment.chaospay-mock`](p4p.payment.chaospay-mock.md) | internal-mock/planned | public capability | operator-only | Declared chaos mock; scenario executor intentionally not enabled yet. |
| [`p4p.payment.godpay-mock`](p4p.payment.godpay-mock.md) | internal-mock | public capability | operator-only | Built-in random success/failure payment debug mock. |
| [`p4p.stock.basic`](p4p.stock.basic.md) | reference | operator | operator-only | Pilot-node stock validation lane. |
| [`p4p.trust.cvr-basic`](p4p.trust.cvr-basic.md) | planned | trust | trust-only | Placeholder trust-claim/CVR lookup manifest. |

## How To Read A Module Page

Each page answers the same questions:

- what does the module do?
- who sees it?
- what data may it access?
- what does it not own?
- what events can it emit?
- how can it be tested locally?
- where are the manifest and provider files?

For raw contract shape, read:

- [`../MODULE-RULES.md`](../MODULE-RULES.md)
- [`../MODULE-PROVIDERS.md`](../MODULE-PROVIDERS.md)
- [`../MODULE-EXECUTION-CONTRACT.md`](../MODULE-EXECUTION-CONTRACT.md)
- [`../COMMUNITY-MODULES.md`](../COMMUNITY-MODULES.md)

For payment-specific rules, read:

- [`../PAYMENT-ADAPTER-STANDARD.md`](../PAYMENT-ADAPTER-STANDARD.md)
- [`../MONEY.md`](../MONEY.md)
