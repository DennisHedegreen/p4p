# p4p.stock.basic

Status: `reference-example`

Status family: `reference`

Manifest: [`../../modules/p4p.stock.basic/module.json`](../../modules/p4p.stock.basic/module.json)

Provider: [`../../modules/p4p.stock.basic/provider.json`](../../modules/p4p.stock.basic/provider.json)

## Purpose

`p4p.stock.basic` is the reference local stock validation lane.

It performs a final local stock check between order acceptance and the next operator lane.

## What It Does

- reads order items
- reads local stock state
- emits `ORDER_VALIDATED` if the order can continue
- emits `ITEM_NOT_POSSIBLE` if an item cannot be fulfilled

## What It Does Not Own

- the public catalog
- customer menu rendering
- payment
- kitchen screen status
- printer/POS handoff
- registry discovery

Stock validation is a local operator workflow. It must not rewrite the customer-facing catalog silently.

## Data Access

Allowed data:

- `order_items`
- `stock_state`

## Events

Inputs:

- `ORDER_ACCEPTED`

Outputs:

- `ORDER_VALIDATED`
- `ITEM_NOT_POSSIBLE`

Failure mode:

- `ITEM_NOT_POSSIBLE`

## Local Test Path

Enable it in the pilot node with `P4P_NODE_MODULES`:

```text
P4P_NODE_MODULES=p4p.stock.basic,p4p.payment.cash
```

The reference pilot-node runtime can execute this lane during local order tests when enabled.

## Current Readiness

This is a test-ready reference module in the pilot-node runtime.

It is not a complete inventory system.
