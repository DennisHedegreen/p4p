# p4p.customer.status

Status: `reference-example`

Status family: `reference`

Manifest: [`../../modules/p4p.customer.status/module.json`](../../modules/p4p.customer.status/module.json)

Provider: [`../../modules/p4p.customer.status/provider.json`](../../modules/p4p.customer.status/provider.json)

## Purpose

`p4p.customer.status` is a customer-facing read-only status surface for submitted orders.

It gives the customer a narrow way to see what happened after an order was sent.

## What It Does

- exposes public order status
- exposes estimated ready time when available
- exposes fulfillment type
- exposes payment method/status summary
- records `ORDER_STATUS_VIEWED`

## What It Does Not Own

- accepting or rejecting orders
- kitchen operations
- payment processing
- customer identity
- customer contact details
- operator-only event logs
- full order notes

The status surface must stay narrow. It is for customer-facing state, not internal restaurant data.

## Data Access

Allowed data:

- `order_id`
- `order_status`
- `estimated_ready`
- `fulfillment_type`
- `payment_method`

Disallowed for the public response:

- customer name
- customer contact
- order note
- internal event log
- operator comments

## Events

Inputs:

- `ORDER_ACCEPTED`
- `ORDER_STATUS_UPDATED`
- `ORDER_REJECTED`
- `ORDER_NEEDS_HUMAN`

Outputs:

- `ORDER_STATUS_VIEWED`

Failure mode:

- `ORDER_STATUS_LOOKUP_FAILED`

## Local Test Path

Enable it in the pilot node with `P4P_NODE_MODULES`:

```text
P4P_NODE_MODULES=p4p.customer.status,p4p.kitchen.screen,p4p.payment.cash
```

Then create an order and open:

```text
GET /p4p/orders/{order_id}
GET /p4p/orders/{order_id}/status
```

## Current Readiness

This is a test-ready reference module in the pilot-node runtime.

It is not a customer account system.
