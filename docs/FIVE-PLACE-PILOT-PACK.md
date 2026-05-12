# Five-Place Pilot Pack

Practical hardware and security pack for the first five Pizza4People pilot locations.

This is not a production rollout plan.

It is a controlled comparison pack for five small restaurant-owned nodes.

The goal is not to prove every hardware idea at once.

The goal is to learn which local operator surfaces actually help a real counter survive direct orders.

## Shared Baseline

All five pilot places should start from the same software truth:

- restaurant-owned `pilot-node`
- `order_mode=menu_only` at first boot
- direct pickup orders only
- `p4p.payment.cash` only
- operator token required for all `/operator/*` data routes
- no online payment
- no delivery orchestration
- no registry-side order relay

Shared baseline module set:

```text
P4P_NODE_MODULES=p4p.catalog.editor,p4p.menu.list,p4p.customer.status,p4p.kitchen.screen,p4p.payment.cash
```

## Version 1: Screen Only

Purpose:

- learn whether the shop can handle direct orders with no printer at all
- learn whether the kitchen screen alone is enough

Preset:

```text
P4P_HARDWARE_PROFILE=operator_screen
P4P_NODE_MODULES=p4p.catalog.editor,p4p.menu.list,p4p.customer.status,p4p.kitchen.screen,p4p.payment.cash
```

Best for:

- very small shop
- owner already works from one laptop or tablet
- lowest hardware risk

Main question:

- do they miss paper, or is a screen enough?

## Version 2: Spool Ticket

Purpose:

- test ticket discipline without raw printer-driver risk
- keep a file-spool artifact that can be inspected after failures

Preset:

```text
P4P_HARDWARE_PROFILE=spool_printer
P4P_NODE_MODULES=p4p.catalog.editor,p4p.menu.list,p4p.customer.status,p4p.kitchen.screen,p4p.payment.cash,p4p.order.print,p4p.order.print.backup
P4P_PRINT_SPOOL_DIR=/var/lib/p4p/print-spool
P4P_BACKUP_PRINT_TARGET=backup_spool
P4P_BACKUP_PRINT_DRIVER=file_spool
P4P_BACKUP_PRINT_SPOOL_DIR=/var/lib/p4p/backup-print-spool
```

Best for:

- shop that wants paper discipline
- shop where Dennis wants strong failure evidence without USB-printer pain yet

Main question:

- is a spool-backed ticket flow enough to uncover the right print behavior before real device rollout?

## Version 3: Screen + Bell

Purpose:

- learn whether a simple alert cue changes operator response enough
- compare silent screen flow vs audible local cue

Preset:

```text
P4P_HARDWARE_PROFILE=operator_screen
P4P_NODE_MODULES=p4p.catalog.editor,p4p.menu.list,p4p.customer.status,p4p.kitchen.screen,p4p.payment.cash,p4p.order.alert.basic
P4P_ALERT_TARGET=counter_bell
P4P_ALERT_MODE=completed
```

Best for:

- noisy counter
- staff who do not stare at the operator screen

Main question:

- does a bell/light reduce missed accepted orders without becoming the actual queue?

## Version 4: Box Printer

Purpose:

- test the first real dedicated node box with ESC/POS printer behavior
- learn whether direct local printing is stable enough for restart and daily service

Preset:

```text
P4P_HARDWARE_PROFILE=box_v1
P4P_NODE_MODULES=p4p.catalog.editor,p4p.menu.list,p4p.customer.status,p4p.kitchen.screen,p4p.payment.cash,p4p.order.print
P4P_PRINT_DEVICE_PATH=/dev/usb/lp0
P4P_PRINT_SENSOR_SERIAL_PATH=/dev/ttyUSB0
```

Best for:

- shop ready to test a dedicated P4P node box
- shop where printer truth matters more than extra surfaces

Main question:

- can a simple dedicated box print reliably enough to trust it during live pickup periods?

## Version 5: Counter Full

Purpose:

- test the strongest first-month local stack in one place
- combine primary print, backup print, alert cue, and pickup board

Preset:

```text
P4P_HARDWARE_PROFILE=box_v1_counter
P4P_NODE_MODULES=p4p.catalog.editor,p4p.menu.list,p4p.customer.status,p4p.kitchen.screen,p4p.payment.cash,p4p.order.print,p4p.order.print.backup,p4p.order.alert.basic,p4p.pickup.board.basic
P4P_PRINT_DEVICE_PATH=/dev/usb/lp0
P4P_PRINT_SENSOR_SERIAL_PATH=/dev/ttyUSB0
P4P_BACKUP_PRINT_SPOOL_DIR=/var/lib/p4p/backup-print-spool
```

`box_v1_counter` currently defaults to:

- ESC/POS raw printer driver
- serial sensor status
- backup spool target
- `counter_bell` alert target
- `counter_screen` pickup-board target

Best for:

- strongest candidate pilot partner
- place where Dennis wants the fullest local feedback in one month

Main question:

- which parts of the full local operator stack are genuinely useful, and which parts are just tool theater?

## Security Baseline

These five places should all follow the same first-month security rules:

1. Do not expose `/operator` on the public internet. Use local network access, Tailscale, WireGuard, or another private admin path.
2. Give every node its own `P4P_OPERATOR_TOKEN`. Do not reuse one token across five shops.
3. Store the env file with `chmod 600`, and treat the operator token like a password.
4. Keep `P4P_NODE_KEY_FILE` separate from the SQLite database path. Back them up separately.
5. Keep `order_mode=menu_only` until the shop explicitly confirms readiness.
6. Use pickup and pay at pickup only for the first month.
7. Do not run online payment, MobilePay adapters, or any merchant-of-record path in the first five-place pack.
8. Do not mirror customer names, contacts, or notes onto pickup-board or registry surfaces.
9. Node-control should stay a private ops surface, not a public fleet dashboard.
10. If orders disappear after reboot, printer output becomes untrustworthy, or operator auth breaks, take that node back out of `live`.

## What To Compare Across The Five Places

Collect the same feedback from each hardware version:

- Were any orders missed?
- Was the kitchen screen enough?
- Did the shop want paper?
- Did the bell/light help or annoy?
- Did the pickup board reduce confusion?
- Could the staff recover after a restart?
- Did the operator understand `menu_only` vs `live`?
- Did any part of the hardware stack create fake confidence instead of real reliability?

## Recommended First Allocation

If Dennis only has five places and one month:

1. give one place `Version 1`
2. give one place `Version 2`
3. give one place `Version 3`
4. give one place `Version 4`
5. give the strongest partner `Version 5`

That gives contrast instead of five copies of the same box.

Read together with:

- `pilot-node/README.md`
- `docs/HARDWARE-STATE-MODEL.md`
- `deploy/pilot-node.env.example`
- `deploy/pilot-node.five-place-presets.env.example`
- `node-control/README.md`
