# p4p.reference

Status: `unsigned-reference`

Manifest: [`../../modules/p4p.catalog.editor/provider.json`](../../modules/p4p.catalog.editor/provider.json)

## Purpose

`p4p.reference` is the shared provider identity for the current in-repo P4P reference modules and internal mock modules.

It is the provider name used for the first public module catalog.

## What It Is

This provider represents:

- reference example modules
- operator-surface reference modules
- public menu and status reference modules
- narrow test-lane modules
- internal mock payment modules used for local debugging

It is a repo-owned reference provider, not an independent commercial provider.

## What It Is Not

`p4p.reference` is not:

- a production certification authority
- proof that all listed modules are live
- proof that all listed modules are safe for real restaurant use
- a payment provider
- a trust authority

## Declared Modules

The current provider manifest declares:

- `p4p.catalog.editor`
- `p4p.catalog.import.ocr`
- `p4p.customer.status`
- `p4p.kitchen.screen`
- `p4p.menu.list`
- `p4p.menu.photo-map`
- `p4p.notify.email`
- `p4p.notify.sms`
- `p4p.order.alert.basic`
- `p4p.order.print`
- `p4p.order.print.backup`
- `p4p.payment.cash`
- `p4p.payment.chaospay-mock`
- `p4p.payment.godpay-mock`
- `p4p.payment.mobilepay`
- `p4p.pickup.board.basic`
- `p4p.stock.basic`
- `p4p.trust.cvr-basic`

## Declared Lanes

The current provider manifest claims support for:

- `public_capability`
- `operator`
- `trust`

That should be read as reference coverage, not production maturity.

For payment-adapter candidates such as `p4p.payment.mobilepay`, that coverage is only a visible module-contract slot plus an external developer invitation. It is not a promise that the reference runtime will own payment integration work.

## Identity And Status

Provider name: `P4P Reference Modules`

Website: <https://github.com/DennisHedegreen/p4p>

Current manifest status: `unsigned-reference`

The current provider manifest has:

- no public key
- no contact value
- no signature

That is acceptable for the current reference catalog.

It is not the end-state provider model described in `MODULE-PROVIDERS.md`.

## Current Readiness

This is a readable provider entry for the current public reference catalog.

It exists so a reader can tell that the current modules mostly come from one shared in-repo reference provider identity, not from a broad provider ecosystem that already exists in production.

That now also includes a small planned pilot-feedback layer for hardware-adjacent operator modules and a future local-payment adapter candidate.
