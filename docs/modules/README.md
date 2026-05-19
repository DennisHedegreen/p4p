# P4P Module Reference

Status: public GitHub reference for the current P4P module manifests.

This directory explains the modules that currently live under `modules/`.

It is not a production module marketplace.

It is not a certification list.

It is not proof that a module is safe for real restaurant use.

The purpose is narrower: make every current module understandable to a new developer or operator without forcing them to inspect raw JSON first.

GitHub is also where the internal mock modules stay visible on purpose.

The public website only shows the current public and pilot-near reading path.

If you only want that public human reading layer first, start at:

- <https://pizza4people.com/modules/>

If you are new to the whole module idea, start here first:

- [`../MODULES-START-HERE.md`](../MODULES-START-HERE.md)

## One Page Per Module

Every current module manifest under `modules/` should have exactly one human-readable page in this directory.

That page is the human layer for the module.

The manifest is still the machine layer.

If a module exists without a matching page here, the public module reference is incomplete.

The corresponding provider identity should also have a matching page under `../providers/`.

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

## Choose Your Path

If you run a shop:

1. [`../MODULES-START-HERE.md`](../MODULES-START-HERE.md)
2. [`p4p.menu.list.md`](p4p.menu.list.md)
3. [`p4p.kitchen.screen.md`](p4p.kitchen.screen.md)
4. [`p4p.payment.cash.md`](p4p.payment.cash.md)

If you want to build a module:

1. [`../MODULES-START-HERE.md`](../MODULES-START-HERE.md)
2. [`../COMMUNITY-MODULES.md`](../COMMUNITY-MODULES.md)
3. [`../MODULE-RULES.md`](../MODULE-RULES.md)
4. [`../MODULE-PROVIDERS.md`](../MODULE-PROVIDERS.md)
5. [`../MODULE-EXECUTION-CONTRACT.md`](../MODULE-EXECUTION-CONTRACT.md)

If you are a skeptical reviewer:

1. [`../MODULES-START-HERE.md`](../MODULES-START-HERE.md)
2. [`../REVIEW-ME.md`](../REVIEW-ME.md)
3. [`p4p.payment.cash.md`](p4p.payment.cash.md)
4. [`p4p.order.print.backup.md`](p4p.order.print.backup.md)
5. [`p4p.pickup.board.basic.md`](p4p.pickup.board.basic.md)

## Current Modules

| Module | Family | Lane | Visibility | Runtime reading | Open this if... |
| --- | --- | --- | --- | --- | --- |
| [`p4p.catalog.editor`](p4p.catalog.editor.md) | reference | operator | operator-only | Pilot-node operator catalog editor for local item truth and menu maintenance. | you want to understand where the shop itself owns menu truth locally. |
| [`p4p.catalog.import.ocr`](p4p.catalog.import.ocr.md) | reference | operator | operator-only | Optional draft OCR/scanned-menu helper beside the catalog editor. | you want to see how paper-menu intake stays draft-only before a human saves truth. |
| [`p4p.customer.status`](p4p.customer.status.md) | reference | public capability | public | Pilot-node customer order-status page/API. | you want the customer follow-up side after a direct order has been sent. |
| [`p4p.kitchen.screen`](p4p.kitchen.screen.md) | reference | operator | operator-only | Pilot-node operator order queue and status updater. | you want to see the kitchen-side state that drives customer status changes. |
| [`p4p.menu.list`](p4p.menu.list.md) | reference | public capability | public | Pilot-node customer list menu. | you want to start from the plainest customer menu lane in the current proof. |
| [`p4p.menu.photo-map`](p4p.menu.photo-map.md) | reference | public capability | public | Pilot-node paper-menu style clickable menu. | you want the more visual paper-menu-style customer surface beside the plain list menu. |
| [`p4p.notify.email`](p4p.notify.email.md) | planned | operator | operator-only | Placeholder notification manifest. | you want to inspect one of the operator-side fallback alert directions, not the public customer loop. |
| [`p4p.notify.sms`](p4p.notify.sms.md) | planned | operator | operator-only | Placeholder phone/SMS fallback notification manifest. | you want to inspect a harsher human fallback lane behind the main operator flow. |
| [`p4p.order.alert.basic`](p4p.order.alert.basic.md) | test | operator | operator-only | Builtin bell/light self-test lane for operator hardware checks. | you want the smallest local alert lane for order-attention hardware. |
| [`p4p.order.print`](p4p.order.print.md) | planned | operator | operator-only | Placeholder printer/POS handoff manifest. | you want to inspect the printer/POS handoff direction behind the queue. |
| [`p4p.order.print.backup`](p4p.order.print.backup.md) | test | operator | operator-only | Builtin backup-printer or spool self-test lane. | you want to see what the operator fallback looks like when the first print lane is not enough. |
| [`p4p.payment.cash`](p4p.payment.cash.md) | reference | public capability | public | Built-in pay-at-pickup/direct-payment adapter. | you want the live payment boundary explained without pretending P4P is a payment company. |
| [`p4p.payment.chaospay-mock`](p4p.payment.chaospay-mock.md) | internal-mock/planned | public capability | operator-only | Declared chaos mock; scenario executor intentionally not enabled yet. | you are reviewing internal failure-testing only. This module stays on GitHub, not the public website. |
| [`p4p.payment.godpay-mock`](p4p.payment.godpay-mock.md) | internal-mock | public capability | operator-only | Built-in random success/failure payment debug mock. | you are reviewing internal payment-debug scaffolding only. This module stays on GitHub, not the public website. |
| [`p4p.payment.mobilepay`](p4p.payment.mobilepay.md) | planned | public capability | public | External-developer invitation for a MobilePay-style payment-adapter manifest. | you want to inspect a future adapter direction without reading it as a live payment claim. |
| [`p4p.pickup.board.basic`](p4p.pickup.board.basic.md) | test | operator | operator-only | Builtin local pickup-board operator surface. | you want to see the local handoff layer between kitchen state and physical pickup. |
| [`p4p.stock.basic`](p4p.stock.basic.md) | reference | operator | operator-only | Pilot-node stock validation lane. | you want to inspect how local stock checks can sit behind the direct ordering flow. |
| [`p4p.trust.cvr-basic`](p4p.trust.cvr-basic.md) | planned | trust | trust-only | Placeholder trust-claim/CVR lookup manifest. | you want to inspect the future business-trust direction without confusing it with the current proof. |

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
