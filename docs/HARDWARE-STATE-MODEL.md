# Hardware State Model

Transition note for node-local hardware state in `pilot-node`.

The setup room no longer lives only on one confirmed hardware-profile string.
The first runtime pass now persists:

- `hardware_profile` as a legacy compatibility bundle id when the chosen shape and add-ons still match a known reference profile
- `hardware_base_profile` as the owner-facing base node shape
- `hardware_enabled_addons` as the owner-facing extra hardware list

Detected devices and richer test-result state are still future work.

The old bundle ids remain:

- `reference_printer`
- `operator_screen`
- `spool_printer`
- `box_v1`
- `box_v1_counter`

That bundle list was enough for the first onboarding pass, but it is too rigid for real shop growth.

The fuller model should separate:

- node shape
- extra hardware capabilities
- what the node can actually see
- what has actually been tested

## Why

The protocol should stay host-agnostic.

That means a valid P4P node could run on:

- Raspberry Pi
- Linux mini-PC
- laptop
- Android-hosted implementation
- another independent implementation entirely

The reference node may remain Pi/Linux-friendly, but the hardware state model should not pretend that one runtime shape is the whole system.

It should also avoid forcing every real-world setup into one rigid bundle.

## Target Layers

The hardware state should be described in four layers.

### 1. Base profile

The base profile answers:

- what is this node fundamentally running as?

Examples:

- `screen_only`
- `printer_box`
- `counter_box`
- `linux_pc`
- `tablet_host`

This is now the main owner-facing replacement for treating `hardware_profile` as the only setup field.

### 2. Add-ons

Add-ons answer:

- what extra local capabilities are intentionally enabled on top of the base profile?

Examples:

- `ticket_printer`
- `backup_spool`
- `order_alert`
- `pickup_board`
- `camera_ocr`
- `second_screen`

Add-ons are not the same thing as modules, but some add-ons may recommend specific modules.

Example:

- `camera_ocr` may suggest `p4p.catalog.import.ocr`
- `pickup_board` may suggest `p4p.pickup.board.basic`
- `order_alert` may suggest `p4p.order.alert.basic`

They should not silently auto-enable runtime modules by themselves.

### 3. Detected devices

Detected devices answer:

- what can this node actually see right now?

Examples:

- printer present on USB
- serial printer sensor present
- second display present
- camera present
- bell target present

This is runtime evidence, not operator intent.

### 4. Test status

Test status answers:

- what has actually been checked by the operator or by a self-test lane?

Examples:

- printer test passed
- bell test failed
- pickup board opened
- OCR preview checked
- first menu reviewed

This should be persistent and timestamped.

## Proposed JSON Shape

This is the recommended future shape for setup/operator state:

```json
{
  "hardware": {
    "base_profile": "screen_only",
    "enabled_addons": [
      "ticket_printer",
      "order_alert"
    ],
    "detected_devices": [
      {
        "device_id": "usb_printer_1",
        "kind": "printer",
        "status": "available",
        "source": "usb",
        "driver": "escpos_raw",
        "label": "USB receipt printer"
      },
      {
        "device_id": "counter_bell_1",
        "kind": "alert_target",
        "status": "available",
        "source": "configured_target",
        "label": "Counter bell"
      }
    ],
    "test_results": {
      "printer_test": {
        "status": "passed",
        "checked_at": "2026-05-11T13:20:00Z"
      },
      "alert_test": {
        "status": "failed",
        "checked_at": "2026-05-11T13:24:00Z"
      },
      "menu_review": {
        "status": "passed",
        "checked_at": "2026-05-11T13:35:00Z"
      }
    },
    "operator_confirmation": {
      "confirmed": true,
      "confirmed_at": "2026-05-11T13:40:00Z",
      "confirmed_by": "local_operator"
    }
  }
}
```

## Current-To-Future Mapping

Current single-string values can be mapped forward like this:

### `reference_printer`

```json
{
  "base_profile": "printer_box",
  "enabled_addons": [],
  "detected_devices": [],
  "test_results": {}
}
```

### `operator_screen`

```json
{
  "base_profile": "screen_only",
  "enabled_addons": [],
  "detected_devices": [],
  "test_results": {}
}
```

### `spool_printer`

```json
{
  "base_profile": "printer_box",
  "enabled_addons": ["backup_spool"],
  "detected_devices": [],
  "test_results": {}
}
```

### `box_v1`

```json
{
  "base_profile": "printer_box",
  "enabled_addons": ["ticket_printer"],
  "detected_devices": [],
  "test_results": {}
}
```

### `box_v1_counter`

```json
{
  "base_profile": "counter_box",
  "enabled_addons": [
    "ticket_printer",
    "backup_spool",
    "order_alert",
    "pickup_board"
  ],
  "detected_devices": [],
  "test_results": {}
}
```

## Proposed Persistence Keys

The current transition layer now stores:

- `setup_hardware_profile`
- `setup_hardware_base_profile`
- `setup_hardware_enabled_addons`

Future SQLite state should still grow toward:

- `setup_hardware_detected_devices`
- `setup_hardware_test_results`
- `setup_hardware_confirmed_at`

The old `setup_hardware_profile` field should remain as a migration and compatibility fallback until the richer structure is fully adopted.

## Relation To Modules

Hardware and modules should stay separate.

Hardware state answers:

- what kind of local box is this?
- what local devices exist?
- what has been tested?

Modules answer:

- what capabilities are enabled in the node runtime?

They overlap, but they are not the same layer.

Example:

- a node may have `camera_ocr` as a hardware add-on
- but `p4p.catalog.import.ocr` may still be disabled in the desired module set

That should be representable without confusion.

## Relation To Implementations

This model is intentionally broader than the current Python reference node.

It should be usable by:

- the current `pilot-node`
- a future Android node implementation
- a Linux desktop node
- an independent third-party node implementation

The important rule is:

- `reference node != only valid node`

## Recommendation

When the next hardware-state pass is built, do not replace the current single dropdown with another single dropdown.

Build toward:

1. `base_profile`
2. `enabled_addons[]`
3. `detected_devices[]`
4. `test_results{}`

That is the simplest structure that can survive real pilot growth without turning into hardware theater.
