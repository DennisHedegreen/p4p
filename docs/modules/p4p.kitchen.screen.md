# p4p.kitchen.screen

Status: `reference-example`

Status family: `reference`

Manifest: [`../../modules/p4p.kitchen.screen/module.json`](../../modules/p4p.kitchen.screen/module.json)

Provider: [`../../modules/p4p.kitchen.screen/provider.json`](../../modules/p4p.kitchen.screen/provider.json)

## Purpose

`p4p.kitchen.screen` is the operator-owned kitchen screen for the pilot node.

It gives the restaurant a local order queue and a way to update order state.

## What It Does

- views incoming order summaries
- views order items and customer contact data needed by the operator
- updates order status
- inspects order events
- records `ORDER_STATUS_UPDATED`

## What It Does Not Own

- public customer menu
- catalog truth
- payment processing
- printer/POS handoff
- customer status page
- registry discovery

The kitchen screen is operator-only. It must not be exposed as a public customer feature.

## Data Access

Allowed data:

- `order_items`
- `note`
- `customer_contact`
- `fulfillment_type`
- `order_status`

This is broader than the customer status module because it is an operator surface.

## Events

Inputs:

- `ORDER_ACCEPTED`
- `ORDER_NEEDS_HUMAN`
- `PRINT_SUCCESS_CONFIRMED`
- `PRINT_UNCERTAIN`
- `PAYMENT_FAILED`

Outputs:

- `ORDER_STATUS_UPDATED`

Failure mode:

- `ORDER_STATUS_UPDATE_FAILED`

## Local Test Path

Enable it in the pilot node with `P4P_NODE_MODULES`:

```text
P4P_NODE_MODULES=p4p.kitchen.screen,p4p.customer.status,p4p.payment.cash
```

Then use:

```text
GET /operator
GET /operator/orders
PATCH /operator/orders/{order_id}
GET /operator/orders/{order_id}/events
```

Operator routes require the operator token.

## Current Readiness

This is a test-ready reference module in the pilot-node runtime.

It is not a production kitchen display system.
