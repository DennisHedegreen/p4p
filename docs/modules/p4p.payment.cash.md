# p4p.payment.cash

Status: `reference-example`

Status family: `reference`

Manifest: [`../../modules/p4p.payment.cash/module.json`](../../modules/p4p.payment.cash/module.json)

Provider: [`../../modules/p4p.payment.cash/provider.json`](../../modules/p4p.payment.cash/provider.json)

## Payment Boundary

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant/operator.

## Purpose

`p4p.payment.cash` is the reference pay-at-pickup/direct-payment adapter.

It marks that payment happens outside the P4P protocol.

## What It Does

- represents cash or direct in-person payment
- reports a local payment mode
- lets the order flow continue without online payment
- records `PAYMENT_MODE_CHANGED`

## What It Does Not Own

- real online payment
- card data
- wallet data
- refunds
- chargebacks
- settlement
- merchant-of-record responsibility

This module does not make P4P a payment provider.

## Data Access

Allowed data:

- `order_total`
- `fulfillment_type`

No payment credentials are needed.

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

Enable it in the pilot node with `P4P_NODE_MODULES` and select it as the active payment module:

```text
P4P_NODE_MODULES=p4p.payment.cash
P4P_PAYMENT_MODULE_ID=p4p.payment.cash
```

Inspect payment module status:

```text
GET /operator/modules
PATCH /operator/modules/payment
```

## Current Readiness

This is a test-ready reference adapter.

It is not online payment.
