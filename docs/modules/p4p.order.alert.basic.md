# p4p.order.alert.basic

Status: `test`

Status family: `test`

Manifest: [`../../modules/p4p.order.alert.basic/module.json`](../../modules/p4p.order.alert.basic/module.json)

Provider: [`../../modules/p4p.order.alert.basic/provider.json`](../../modules/p4p.order.alert.basic/provider.json)

## Purpose

`p4p.order.alert.basic` is a planned local bell/light alert module.

It describes a very simple hardware-adjacent lane that can beep, ring, or flash when a new order or hardware problem needs attention.

## What It Would Do

- receive accepted-order or hardware-failure events
- trigger a configured local sound/light target
- report whether the local alert action completed
- retry or fall back when the local alert path is unavailable

## What It Does Not Own

- customer menu
- order acceptance
- kitchen state
- payment
- restaurant identity

An alert is only a cue. It must not become the actual queue or decision layer.

## Data Access

Planned data:

- `order_summary`
- `alert_target`

This should stay small and operational.

## Events

Inputs:

- `ORDER_ACCEPTED`
- `ORDER_NEEDS_HUMAN`
- `PRINTER_OFFLINE`
- `PRINT_TIMEOUT`
- `PAPER_OUT`

Outputs:

- `OUTBOUND_ACTION_REQUESTED`
- `ACTION_COMPLETED`
- `RETRY_SCHEDULED`

Failure mode:

- `NODE_CONNECTIVITY_LOST`

## Local Test Path

A builtin reference self-test path now exists in `pilot-node`.

It does not yet subscribe automatically to every live order or hardware event.

It does let the operator test whether a simple bell/light target is worth carrying into five-place hardware feedback.

Required configuration:

```text
alert_target
```

## Current Readiness

This is now a builtin reference self-test lane.

It is still not the main operator queue or a full event-subscription runtime.
