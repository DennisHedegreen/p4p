# p4p.pickup.board.basic

Status: `test`

Status family: `test`

Manifest: [`../../modules/p4p.pickup.board.basic/module.json`](../../modules/p4p.pickup.board.basic/module.json)

Provider: [`../../modules/p4p.pickup.board.basic/provider.json`](../../modules/p4p.pickup.board.basic/provider.json)

## Purpose

`p4p.pickup.board.basic` is a planned local pickup-board module.

It describes a simple screen facing the counter that can show which direct orders are accepted or ready.

## What It Would Do

- receive accepted, updated, or rejected order-state events
- render a small local board for staff/customer pickup flow
- mirror payment-mode or ready-time information that is safe to show publicly at the counter
- retry or fall back when the local display path disappears

## What It Does Not Own

- customer discovery
- new order creation
- the kitchen queue
- payment settlement
- restaurant identity

This is a local presentation lane, not the main operator source of truth.

## Data Access

Planned data:

- `order_summary`
- `order_status`
- `estimated_ready_time`
- `payment_method`
- `pickup_board_target`

It should only expose the narrow order-facing facts that make sense at the pickup counter.

## Events

Inputs:

- `ORDER_ACCEPTED`
- `ORDER_STATUS_UPDATED`
- `ORDER_REJECTED`
- `PAYMENT_MODE_CHANGED`

Outputs:

- `OUTBOUND_ACTION_REQUESTED`
- `ACTION_COMPLETED`
- `RETRY_SCHEDULED`

Failure mode:

- `NODE_CONNECTIVITY_LOST`

## Local Test Path

A builtin local counter surface now exists in `pilot-node`.

When enabled and configured, the operator can open `/operator/pickup-board` and read the filtered accepted/ready queue.

Required configuration:

```text
pickup_board_target
```

## Current Readiness

This is now a builtin local operator surface.

It is still not the kitchen source of truth. It is the narrow counter-facing mirror.
