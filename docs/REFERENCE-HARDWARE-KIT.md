# P4P Reference Hardware Kit

Status: procurement and bench-test candidate, not production hardware.

This document turns the existing hardware profiles into physical reference
shapes for the first controlled restaurant pilot. It does not make Raspberry Pi
the protocol requirement. A conforming P4P node may run on other hardware or be
implemented independently.

## What The Hardware Must Prove

The first box does not need to become a complete point-of-sale system.

It must prove that a restaurant can:

- keep its node and order history under its own control
- see a new pickup order at the counter
- accept, reject, mark ready, complete, and cancel an order
- return safely after application and power restarts
- switch quickly between `menu_only`, `live`, and closed operation
- keep operator credentials off the public customer surface
- continue to be discoverable through two registries

The hardware is successful only when the counter can trust it during a real
service period.

## Screen And Host Are Separate Decisions

A smartphone or tablet can be the operator screen without being the node host.
It opens the node's operator interface in a browser over the local network.

This means the first local node does not need a dedicated touch display.

Bluetooth is not the preferred display path. The phone is a normal web client
over Wi-Fi or Ethernet-backed local networking. A phone hotspot may be used in a
short connectivity experiment, but it is not the reference pilot network:

- mobile connections commonly sit behind carrier NAT
- the public node still needs stable HTTPS reachability
- hotspot sleep, charging, and roaming add failure modes
- one phone should not be both the only network and the only operator screen

## Reference Shapes

### Shape 0: Existing Screen, Hosted Node

Physical parts:

- existing laptop, tablet, or phone
- existing restaurant internet
- hosted `pilot-node`

Use this for the first operator-flow rehearsal. It is the cheapest path to real
counter feedback, but it must be described as a hosted restaurant node rather
than full restaurant self-hosting.

Maps to:

- base profile: `screen_only`
- required add-ons: none

### Shape 1: Local Reference Node

Candidate bill of materials:

| Part | Requirement | Current candidate | Evidence state |
| --- | --- | --- | --- |
| Node computer | 64-bit Linux, stable networking, enough memory for the Python node | Raspberry Pi 4 Model B, 1 GB or 2 GB | Candidate; physical load test required |
| Power | Stable supply sized for board and USB load | Official-quality 5 V / 3 A USB-C supply | Supported by Pi 4 specification |
| Storage | Persistent SQLite, keys, logs, and spool | 32 GB high-endurance microSD for bench; USB SSD as reliability comparison | Candidate; power-loss test required |
| Network | Stable restaurant LAN | Gigabit Ethernet preferred; Wi-Fi accepted for comparison | Pi 4 capability; pilot behavior untested |
| Enclosure | Protect board without trapping heat | Vented case; fan only if temperature evidence requires it | Candidate |
| Operator screen | Browser access to `/operator` on a private path | Existing phone or tablet | Supported by current operator UI |

Why Pi 4 is the reference candidate:

- it has Ethernet and four full-size USB ports
- it avoids adapters and hubs for the first printer experiment
- 1 GB and 2 GB variants allow us to test the smallest sensible memory shape
- Raspberry Pi states that Pi 4 remains in production until at least January
  2034

The 1 GB model is a cost candidate, not yet an accepted minimum. The 2 GB model
is the safer first physical purchase if only one box is being assembled.

Maps to:

- base profile: `screen_only`
- optional next profile: `printer_box`

### Shape 2: Local Print Box

Add to Shape 1:

| Part | Requirement | Current candidate | Evidence state |
| --- | --- | --- | --- |
| Receipt printer | USB-accessible ESC/POS-compatible printer with its own supply | USB thermal printer; exact model not selected | Driver exists; no physical printer accepted |
| Paper | Correct thermal roll for selected printer | Model-specific | Not selected |
| Cable | Stable data cable, strain relieved | Model-specific USB cable | Not selected |
| Backup | Preserve a ticket if printing is uncertain | Existing file-spool lane | Implemented locally |

The existing `escpos_raw` driver writes directly to a configured Linux device
path and supports no cut, full cut, or partial cut. That does not prove every
printer advertised as ESC/POS-compatible will work. The selected printer must
pass the bench matrix below.

Adafruit's Tiny Thermal Receipt Printer is a useful prototype candidate because
its documentation includes a USB interface for Linux and Raspberry Pi. It is
not yet the P4P reference printer, and its device behavior must be tested before
it appears in a purchase or sponsor request.

Maps to:

- base profile: `printer_box`
- enabled add-ons: `ticket_printer`, optionally `backup_spool`

### Shape 3: Counter Box

Add only after Shape 2 is reliable:

- local order alert
- pickup-board screen
- backup print spool
- optional small uninterruptible power supply

Maps to:

- base profile: `counter_box`
- enabled add-ons: `ticket_printer`, `backup_spool`, `order_alert`,
  `pickup_board`

This is not the first purchase target. It is the strongest comparison shape in
the existing five-place pilot pack.

## Pi Zero 2 W Boundary

Raspberry Pi Zero 2 W is a useful lower-bound experiment, not the default box.
It has a quad-core 64-bit processor and 512 MB RAM, but only one USB 2.0 OTG data
interface, 2.4 GHz Wi-Fi, and no built-in Ethernet.

It should be accepted only if it passes:

- cold boot and automatic node start
- pilot-readiness checks under the real configuration
- 48-hour process and memory observation
- restart with orders preserved
- operator use while orders arrive
- printer use without an unstable hub, if printing is in scope

Until then, `Pi Zero 2 W compatible` is a hypothesis, not a project claim.

## Network Boundary

The local box must serve two different paths:

1. public customer traffic to the node's menu, order, status, and info routes
2. private operator traffic to `/operator/*`

The first physical build must choose and document one HTTPS reachability model.
Candidates include a restaurant-controlled public connection, a narrowly
configured reverse path, or a hosted node for the first rehearsal. The choice
must preserve the claim that orders go directly to the restaurant-designated
node and must not expose the operator surface.

Phone hotspot connectivity alone does not resolve this requirement.

## Bench Acceptance Matrix

No physical shape becomes a reference kit until a dated receipt records these
checks:

| Check | Minimum acceptance |
| --- | --- |
| Clean boot | Node starts without keyboard or monitor |
| Application restart | Menu, configuration, and orders remain present |
| Power interruption | SQLite integrity passes and no accepted order disappears |
| Operator privacy | Operator data rejects unauthenticated access |
| Mode control | Operator can move between `menu_only`, `live`, and closed |
| Dual discovery | Both configured registries can discover the same node |
| Registry failure | Backup discovery still works |
| Order path | Order reaches the node without registry order relay |
| Duplicate retry | Same request id does not create a second order |
| Counter visibility | Staff notices and can process a new order |
| Network loss | Failure is visible and recovery does not create duplicates |
| Thermal behavior | No throttling or unsafe temperature during service test |
| Printer, if fitted | 20 consecutive tickets, paper-out, reconnect, and reboot tested |
| Backup, if fitted | File spool remains readable after print uncertainty |

The existing `scripts/check-pilot-readiness.py` remains the software gate. The
bench receipt adds physical evidence; it does not replace the software gate.

## Purchase Order

Do not buy five identical boxes first.

Recommended sequence:

1. rehearse Shape 0 with the current software
2. buy or obtain one Pi 4 reference box without a dedicated display
3. run the constrained and physical acceptance matrix
4. add one USB printer and test it separately
5. decide whether screen-only, print box, or counter box deserves replication
6. only then prepare a three-kit sponsor request

## Sponsor Request Boundary

A later hardware request should ask for a defined physical experiment, not
general project support.

The request should contain:

- exact quantities and part numbers
- the public P4P repository and protocol explanation
- the controlled-pilot boundary
- the tests the donated hardware will undergo
- the public, honest report that will result
- no promise of endorsement or production certification

Potential contacts include Raspberry Pi's industry channel, Adafruit's maker
community, and European Raspberry Pi or open-hardware distributors. No current
free-hardware programme has been confirmed.

## Source Notes

- Raspberry Pi 4 specification:
  <https://www.raspberrypi.com/products/raspberry-pi-4-model-b/specifications/>
- Raspberry Pi Zero 2 W documentation:
  <https://www.raspberrypi.com/documentation/computers/zero.html>
- Raspberry Pi computer power documentation:
  <https://www.raspberrypi.com/documentation/computers/raspberry-pi.html>
- Adafruit thermal-printer guide:
  <https://learn.adafruit.com/mini-thermal-receipt-printer>

## Open Decisions

- Pi 4 1 GB versus 2 GB after a constrained-memory test
- high-endurance microSD versus USB SSD after power-loss testing
- exact USB ESC/POS printer model
- stable HTTPS path for an on-premises restaurant node
- whether an audible alert is necessary when a phone or tablet is the screen
- whether the first physical box needs a small UPS
