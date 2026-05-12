# p4p.payment.mobilepay

Status: `planned`

Status family: `planned`

Manifest: [`../../modules/p4p.payment.mobilepay/module.json`](../../modules/p4p.payment.mobilepay/module.json)

Provider: [`../../modules/p4p.payment.mobilepay/provider.json`](../../modules/p4p.payment.mobilepay/provider.json)

## Purpose

`p4p.payment.mobilepay` is a planned external-developer payment-adapter slot.

It describes a future MobilePay-style pay-at-pickup or local direct-payment instruction that could be added after cash-first pilot feedback, but it is not a promise that the P4P reference runtime will implement or operate it.

## What It Would Do

- receive payment-mode requirements
- expose a MobilePay-style payment mode chosen by the restaurant/operator
- report payment-mode changes or payment failure
- fall back to simpler payment lanes when the operator disables the adapter

## What It Does Not Own

- customer menu
- order creation
- settlement
- merchant-of-record responsibility
- restaurant identity

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant/operator.

If this adapter is ever built, it should be owned by an external developer, integrator, or operator-side provider, not by P4P core.

## Data Access

Planned data:

- `order_total`
- `fulfillment_type`
- `payment_destination`

The declared data should stay at the payment-mode level. No card or account credentials belong here.

## Developer Call Boundary

This module should be read as an invitation to external developers, not as a promise that P4P wants to become the payment actor.

P4P should stay the motorway:

- discovery
- direct menu fetch
- direct order handoff
- module declaration

The adapter provider should own:

- payment API integration
- merchant setup
- capture/cancel/refund behavior
- payment-specific operational and compliance burden

See also: [`../MOBILEPAY-DEVELOPER-CALL.md`](../MOBILEPAY-DEVELOPER-CALL.md)

## Events

Inputs:

- `PAYMENT_REQUIRED`
- `PAYMENT_FAILED`

Outputs:

- `PAYMENT_MODE_CHANGED`
- `PAYMENT_FAILED`

Failure mode:

- `PAYMENT_FAILED`

## Local Test Path

No executable reference path exists yet.

The manifest declares required configuration:

```text
payment_destination
```

## Current Readiness

This is placeholder manifest material for pilot feedback after the cash-first lane.

It is not enabled in the reference runtime.

It is an external-developer invitation, not a P4P-owned payment runtime promise.
