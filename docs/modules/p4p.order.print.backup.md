# p4p.order.print.backup

Status: `test`

Status family: `test`

Manifest: [`../../modules/p4p.order.print.backup/module.json`](../../modules/p4p.order.print.backup/module.json)

Provider: [`../../modules/p4p.order.print.backup/provider.json`](../../modules/p4p.order.print.backup/provider.json)

## Purpose

`p4p.order.print.backup` is a planned backup print-path module.

It describes how a restaurant could keep a second printer target or local spool ready when the first print path fails.

## What It Would Do

- receive print failure events from the primary print lane
- reroute the order to a secondary printer target or spool
- report whether the fallback print path succeeded or failed
- trigger human/operator fallback modules if the backup path also fails

## What It Does Not Own

- customer menu
- order creation
- payment
- kitchen state
- restaurant identity

This is a resilience module around hardware failure, not a new order source of truth.

## Data Access

Planned data:

- `order_items`
- `note`
- `customer_contact`
- `fulfillment_type`
- `backup_printer_target`

It should receive enough order detail to print a useful ticket, but not unrelated payment data.

## Events

Inputs:

- `PRINTER_OFFLINE`
- `PRINT_TIMEOUT`
- `PAPER_OUT`
- `PRINT_UNCERTAIN`

Outputs:

- `PRINT_SUCCESS_CONFIRMED`
- `PRINT_FAILED_PRECHECK`
- `PRINT_UNCERTAIN`
- `PRINTER_OFFLINE`
- `PAPER_LOW`
- `PAPER_OUT`
- `PAPER_JAM`
- `PRINT_TIMEOUT`

## Local Test Path

A builtin reference self-test path now exists in `pilot-node`.

It does not yet auto-reroute live print failures inside the ordinary order flow.

It does let the operator test a secondary target or spool path before a restaurant starts giving hardware feedback.

Required configuration:

```text
backup_print_target
```

Typical extra configuration depends on the chosen driver:

- `backup_print_spool_dir` for `file_spool`
- `backup_print_device_path` for `device_path` or `escpos_raw`

The current purpose is narrower: make backup-print behavior reviewable before five pilot locations start giving hardware feedback.

## Current Readiness

This is now a builtin reference self-test lane.

It is still not a full automatic live fallback print executor.
