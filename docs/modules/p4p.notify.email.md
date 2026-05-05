# p4p.notify.email

Status: `planned`

Status family: `planned`

Manifest: [`../../modules/p4p.notify.email/module.json`](../../modules/p4p.notify.email/module.json)

Provider: [`../../modules/p4p.notify.email/provider.json`](../../modules/p4p.notify.email/provider.json)

## Purpose

`p4p.notify.email` is a planned operator notification module.

It describes a future module that can send order or failure notifications to an operator-controlled email address.

## What It Would Do

- receive order and failure events
- send an operator notification
- report `NOTIFICATION_SENT` or `NOTIFICATION_FAILED`
- provide a fallback path when printer or primary order surfaces fail

## What It Does Not Own

- order acceptance
- kitchen state
- payment
- customer menu
- registry discovery
- restaurant identity

Notification is side-work. It must not become the order source of truth.

## Data Access

Planned data:

- `order_summary`
- `operator_destination`

It should only receive enough data to notify the operator.

## Events

Inputs:

- `ORDER_ACCEPTED`
- `ORDER_NEEDS_HUMAN`
- `PRINTER_OFFLINE`
- `PRINT_TIMEOUT`
- `PAPER_OUT`

Outputs:

- `NOTIFICATION_SENT`
- `NOTIFICATION_FAILED`

Failure mode:

- `NOTIFICATION_FAILED`

## Local Test Path

No executable reference path exists yet.

The manifest declares required configuration:

```text
operator_destination
```

## Current Readiness

This is placeholder manifest material.

It is not enabled in the reference runtime.
