# p4p.notify.sms

Status: `planned`

Status family: `planned`

Manifest: [`../../modules/p4p.notify.sms/module.json`](../../modules/p4p.notify.sms/module.json)

Provider: [`../../modules/p4p.notify.sms/provider.json`](../../modules/p4p.notify.sms/provider.json)

## Purpose

`p4p.notify.sms` is a planned SMS fallback notification module.

It describes a future path for sending order or hardware-failure notifications to an operator-controlled phone destination.

## What It Would Do

- receive order and failure events
- send an operator SMS
- report `NOTIFICATION_SENT` or `NOTIFICATION_FAILED`
- provide a phone fallback when printer or local hardware surfaces fail

## What It Does Not Own

- order acceptance
- kitchen state
- payment
- customer menu
- registry discovery
- restaurant identity

SMS is fallback communication, not the order loop itself.

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

This is placeholder manifest material for multi-site pilot feedback.

It is not enabled in the reference runtime.
