# p4p.payment.godpay-mock

Status: `internal-mock`

Status family: `internal-mock`

Manifest: [`../../modules/p4p.payment.godpay-mock/module.json`](../../modules/p4p.payment.godpay-mock/module.json)

Provider: [`../../modules/p4p.payment.godpay-mock/provider.json`](../../modules/p4p.payment.godpay-mock/provider.json)

## Payment Boundary

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant/operator.

`p4p.payment.godpay-mock` is not real money, not real settlement, not a wallet, not crypto, and not a production payment method.

## Purpose

`p4p.payment.godpay-mock` is an internal random approval/failure mock for local debugging.

The user asks the pizza gods whether the test payment goes through.

## What It Does

- generates a roll from `1` to `100`
- compares the roll to a configured success threshold
- accepts or rejects the internal test payment
- records the roll, threshold, and outcome
- emits either `PAYMENT_MODE_CHANGED` or `PAYMENT_FAILED`

Suggested messages:

- success: "The pizza gods accepted the offering."
- failure: "The pizza gods declined this order."

## What It Does Not Own

- real payment provider integration
- funds movement
- customer wallets
- card data
- settlement
- refunds
- production payment decisions

It exists to test UI and order-state behavior.

## Data Access

Allowed data:

- `order_total`

No payment credentials are needed.

## Events

Inputs:

- `PAYMENT_REQUIRED`

Outputs:

- `PAYMENT_MODE_CHANGED`
- `PAYMENT_FAILED`

Failure mode:

- `PAYMENT_FAILED`

## Local Test Path

Enable it in the pilot node and select it as the active payment module:

```text
P4P_NODE_MODULES=p4p.payment.cash,p4p.payment.godpay-mock
P4P_PAYMENT_MODULE_ID=p4p.payment.godpay-mock
P4P_GODPAY_SUCCESS_THRESHOLD=50
```

Optional debugging knobs:

```text
P4P_GODPAY_SEED=123
P4P_GODPAY_FORCE_ROLL=42
```

Inspect module status:

```text
GET /operator/modules
PATCH /operator/modules/payment
```

## Current Readiness

This is executable in the pilot node when explicitly selected.

It is internal debug infrastructure only.
