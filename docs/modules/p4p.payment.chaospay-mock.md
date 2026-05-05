# p4p.payment.chaospay-mock

Status: `internal-mock-planned`

Status family: `internal-mock`

Manifest: [`../../modules/p4p.payment.chaospay-mock/module.json`](../../modules/p4p.payment.chaospay-mock/module.json)

Provider: [`../../modules/p4p.payment.chaospay-mock/provider.json`](../../modules/p4p.payment.chaospay-mock/provider.json)

## Payment Boundary

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant/operator.

`p4p.payment.chaospay-mock` is not real money, not real settlement, not a wallet, not crypto, and not a production payment method.

## Purpose

`p4p.payment.chaospay-mock` is a planned internal chaos payment mock.

It is meant to stress-test ugly payment edge cases after the basic payment state machine is stable.

## Planned Scenarios

The module is intended to simulate cases such as:

- instant success
- user cancellation
- provider timeout
- duplicate callback
- late callback after order expiry
- wrong amount
- wrong currency
- invalid signature
- provider says paid after order cancellation
- merchant confirms without valid payment
- status changes out of order
- conflicting callbacks

## What It Does Not Own

- real payment provider integration
- funds movement
- customer wallets
- card data
- settlement
- refunds
- production payment decisions

The purpose is to break assumptions in the P4P order/payment flow, not to simulate money.

## Data Access

Planned data:

- `order_total`
- `order_status`

No real customer funds or provider credentials should enter this module.

## Events

Inputs:

- `PAYMENT_REQUIRED`

Outputs:

- `PAYMENT_MODE_CHANGED`
- `PAYMENT_FAILED`

Failure mode:

- `PAYMENT_FAILED`

## Local Test Path

The manifest is present, but the scenario executor is intentionally not enabled yet.

The manifest declares required configuration:

```text
scenario
```

## Current Readiness

Declared only.

Use `p4p.payment.godpay-mock` for simple payment-state debugging first.
