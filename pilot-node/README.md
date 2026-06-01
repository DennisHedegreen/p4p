# pilot-node

Restaurant-owned node for the first controlled live pilot.

This is not the demo node.

It is also not the public proof node.

It is the smallest real node shape for one restaurant:

- persistent menu
- persistent orders
- operator-token protected controls
- operator catalog editor
- signed announce
- signed heartbeat
- pickup orders
- pay at pickup
- optional stock validation lane
- optional catalog editor operator surface
- optional OCR/scanned-menu draft import helper beside the catalog editor
- optional customer list-menu surface
- optional customer photo-map menu surface
- optional pay-at-pickup payment-mode lane
- optional kitchen-screen operator surface
- optional customer order-status surface
- optional backup print self-test lane
- optional local alert self-test lane
- optional pickup-board counter surface

Start it in `menu_only`.

Move to `live` only through explicit operator action.

Internal package layout:

- `pilot_node.py` is the room-level launcher module
- `app/pilot_node/` holds the importable runtime package behind that launcher

## Local Run

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/python -m pip install -r requirements-ocr.txt  # optional image OCR preview
P4P_PILOT_NODE_DB_PATH=/tmp/p4p-pilot-node.sqlite3 \
P4P_OPERATOR_TOKEN=change-this \
P4P_REGISTRY_URLS=http://127.0.0.1:8000,http://127.0.0.1:8002 \
P4P_NODE_BASE_URL=http://127.0.0.1:8201 \
P4P_NODE_ORDER_MODE=menu_only \
./.venv/bin/uvicorn pilot_node:app --port 8201
```

The SQLite path is the pilot node's source of truth for menu, operator state,
active payment-module selection, and order history.

For the first five hardware-pilot variants and the security baseline around them,
read `docs/FIVE-PLACE-PILOT-PACK.md`, `docs/HARDWARE-STATE-MODEL.md`, and `deploy/pilot-node.five-place-presets.env.example`.

Enable the small reference runtime lanes with `P4P_NODE_MODULES`:

- `p4p.catalog.editor` exposes the built-in operator catalog editor for item ids, prices, categories, active availability, and optional item image URLs.
- `p4p.catalog.import.ocr` exposes the built-in operator draft OCR text/image import preview on its own dedicated module page beside the catalog editor.
- install `requirements-ocr.txt` if `p4p.catalog.import.ocr` should preview draft catalog lines from a photographed or scanned paper menu
- `p4p.menu.list` exposes the built-in customer list-menu page from active catalog items and renders optional item images.
- `p4p.menu.photo-map` exposes the built-in customer paper-menu style page from active catalog items and renders optional item images.
- `p4p.stock.basic` emits `ORDER_VALIDATED`, or `ITEM_NOT_POSSIBLE` when a configured item is unavailable.
- `p4p.customer.status` exposes read-only public order status without customer contact details, notes, or operator event logs.
- `p4p.kitchen.screen` exposes the built-in operator order queue for kitchen status updates.
- `p4p.payment.cash` emits `PAYMENT_REQUIRED -> PAYMENT_MODE_CHANGED` for pay-at-pickup, or `PAYMENT_FAILED` when `P4P_PAYMENT_CASH_MODE=failed`.
- `p4p.payment.godpay-mock` emits a random internal test payment success/failure based on `P4P_GODPAY_SUCCESS_THRESHOLD`.
- `p4p.payment.chaospay-mock` is declared as a planned internal chaos-payment mock, but its scenario executor is intentionally not enabled yet.
- `p4p.order.print` emits the operator print/screen lane.
- `p4p.order.print.backup` exposes a builtin operator self-test for a backup printer/spool target.
- `p4p.order.alert.basic` exposes a builtin operator self-test for a bell/light target.
- `p4p.pickup.board.basic` exposes a builtin local `/operator/pickup-board` surface for accepted/ready orders.

These lanes do not add online payment, card handling, real wallet handling, settlement, or registry access to order contents.

Homebuilt or external module IDs can also be listed in `P4P_NODE_MODULES`.
If a module has no reference manifest, the pilot node keeps it as `undeclared_modules`
in operator state and does not execute or publish it as a P4P reference module.

The operator can now import a local `module.json` into node-local SQLite metadata from
`GET /operator/import`, but phase 1 keeps imported manifests as metadata only.
They are visible on the node, but are not runnable, do not enter `available_modules`,
and do not become selectable for the desired runtime set yet.

The first test path is `local.pizzacoin.wallet`, which remains outside `P4P/`.

Example local Pizzacoin payment startup default:

```bash
P4P_NODE_MODULES=p4p.payment.cash,local.pizzacoin.wallet,p4p.order.print \
P4P_EXTERNAL_MODULE_MANIFESTS="../../Pizzacoin/contracts/module.json" \
P4P_PAYMENT_MODULE_ID=local.pizzacoin.wallet \
P4P_PAYMENT_EXTERNAL_CUSTOMER_USER_ID=usr_from_pizzacoin_gui \
./.venv/bin/uvicorn pilot_node:app --port 8201
```

`P4P_PAYMENT_MODULE_ID` is only the startup default. The operator dashboard can
switch the active payment module later with `PATCH /operator/modules/payment`,
and that choice persists in the node SQLite database.

The enabled module set also has a node-local source of truth in SQLite.

- `P4P_NODE_MODULES` is the bootstrap fallback
- the operator can persist a desired module set with `PATCH /operator/modules/set`
- that desired set applies on the next node restart
- the running runtime and the desired-after-restart set are shown separately in the operator

This keeps module selection honest across local dev, systemd, and simple hosted launch modes.

The setup/onboarding layer also has a node-local source of truth in SQLite.

- `GET /operator/setup` returns the computed setup summary as JSON for the operator shell
- `PATCH /operator/setup` persists the small onboarding record beside runtime state
- the remembered onboarding state also stores one operator locale so the tablet can stay in Danish, Swedish, Turkish, Arabic, or Kurdish between refreshes
- the next-step split between locale engine, shell language packs, and per-node custom overrides is documented in `docs/LANGUAGE-PACKS-v2.md`
- the first on-disk scaffold for that split now lives under `data/i18n/`
- setup state is not the source of truth for menu, modules, or orders; it is a remembered owner-facing checklist layer on top of them
- hardware setup state now persists a richer owner-facing shape beside the legacy bundle id:
  - `hardware_profile` remains as a compatibility bundle field when the chosen base shape and add-ons still match a known reference profile
  - `hardware_base_profile` stores the chosen node shape such as `screen_only`, `printer_box`, or `counter_box`
  - `hardware_enabled_addons` stores the chosen extra local hardware capabilities such as `ticket_printer`, `backup_spool`, `order_alert`, or `pickup_board`
  - detected devices and richer hardware test results still belong to the next pass documented in `docs/HARDWARE-STATE-MODEL.md`

In that mode the payment lane posts to the manifest `entrypoint`, auto-confirms
the fake payment by default, and emits `PAYMENT_REQUIRED -> PAYMENT_MODE_CHANGED`
or `PAYMENT_FAILED -> ORDER_NEEDS_HUMAN`.

The external HTTP payment executor is guarded:

- the selected module must be enabled in `P4P_NODE_MODULES`
- the module manifest must be imported with `P4P_EXTERNAL_MODULE_MANIFESTS`
- the startup default or operator-selected active payment module must name that imported module
- plain `http` entrypoints are accepted only on loopback hosts
- `P4P_PAYMENT_EXTERNAL_CUSTOMER_USER_ID` must be set for the fake wallet test

Example internal GodPay mock startup default:

```bash
P4P_NODE_MODULES=p4p.payment.godpay-mock,p4p.order.print \
P4P_PAYMENT_MODULE_ID=p4p.payment.godpay-mock \
P4P_GODPAY_SUCCESS_THRESHOLD=50 \
./.venv/bin/uvicorn pilot_node:app --port 8201
```

GodPay is only an internal debug mock. It logs the roll, threshold, and outcome
on the payment event. It is not money, not settlement, and not a provider.

## Order States

The first pilot order-state set is:

- `new`
- `accepted`
- `rejected`
- `ready`
- `completed`
- `cancelled`

## Public Endpoints

- `GET /`
- `GET /health`
- `GET /p4p/menu`
- `GET /p4p/assets/food-image-fixtures/{asset_path}` for local synthetic PNG test fixtures
- `GET /p4p/menu/list`
- `GET /p4p/menu/photo-map`
- `POST /p4p/order`
- `GET /p4p/orders/{order_id}`
- `GET /p4p/orders/{order_id}/status`
- `GET /p4p/info`

## Operator Endpoints

All operator endpoints require either:

- `Authorization: Bearer <token>`
- `X-P4P-Operator-Token: <token>`

Endpoints:

- `GET /operator/welcome`
- `GET /operator/setup`
- `PATCH /operator/setup`
- `GET /operator`
- `GET /operator/catalog`
- `GET /operator/discover`
- `GET /operator/import`
- `GET /operator/modules/view/{module_id}`
- `GET /operator/node`
- `GET /operator/pickup-board`
- `GET /operator/pickup-board/data`
- `GET /operator/state`
- `PATCH /operator/state`
- `GET /operator/modules` (HTML page in the browser, JSON for operator fetches)
- `GET /operator/modules/imports`
- `POST /operator/modules/import-manifest`
- `DELETE /operator/modules/imports/{module_id}`
- `GET /operator/modules/{module_id}`
- `POST /operator/modules/{module_id}/self-test`
- `PATCH /operator/modules/payment`
- `PATCH /operator/modules/set`
- `GET /operator/menu`
- `POST /operator/menu/import-preview`
- `POST /operator/menu/import-image-preview`
- `PUT /operator/menu`
- `GET /operator/orders`
- `GET /operator/orders/{order_id}/events`
- `PATCH /operator/orders/{order_id}`
- `POST /operator/reannounce`

`GET /operator/welcome` is the owner-first intro room, and
`GET /operator/setup` is the first computed setup-checklist room.
`PATCH /operator/setup` persists the small onboarding state for that room
(such as chosen operator language, chosen base hardware shape, chosen extra hardware, menu reviewed, and local tests run).
`GET /operator` now serves the local operations room.
`GET /operator/catalog` serves the dedicated catalog room, and
`GET /operator/modules` serves the dedicated module-control room.
`GET /operator/discover` is the read-only bridge into the public module catalog on `protocols4people.com/modules`,
`GET /operator/import` is the metadata-only room for uploading a local module manifest onto this node,
and `GET /operator/node` keeps local node identity, setup truth, and restart state in one room.
The HTML shells are readable without a token, but all operator data requests
still require the operator token.

The operator module panel is owner-first:

- operations, catalog work, and module control no longer live on one long mixed page
- current modules and available modules are shown separately
- each module has a dedicated operator page at `GET /operator/modules/view/{module_id}`
- `GET /operator/modules/{module_id}` returns the JSON detail for that page
- `PATCH /operator/modules/set` updates the desired module set in SQLite
- general module changes are restart-applied, not silently hot-swapped in-process
- imported manifests live in a separate node-local metadata lane until a later phase makes imported modules runnable

When `p4p.catalog.import.ocr` is enabled and OCR dependencies are installed, the
dedicated module page at `GET /operator/modules/view/p4p.catalog.import.ocr`
can upload a menu photo, preview draft items, and save selected draft items into
the catalog. If the module is not enabled, the OCR preview routes return `404`
and the generic operator shell does not show photo-import controls.

## Local Dry Run

Use `TEST-GUIDE.md` as the canonical sequence.

The minimum local pilot dry run is:

1. run primary and backup registries
2. start `pilot-node` with SQLite and an operator token
3. confirm `/operator/state` requires the token
4. move the node from `menu_only` to `live`
5. submit a pickup order directly to `/p4p/order`
6. inspect `/operator/orders`
7. move the order through `accepted`, `ready`, and `completed`
8. restart the node and confirm the stored order is still present
9. return the node to `menu_only` or set `open=false`

## Pilot Rules

- Use `order_mode=menu_only` until the restaurant is ready.
- Use `order_mode=live` only after the operator has confirmed readiness.
- Use pickup and pay at pickup for the first pilot.
- Do not expose the operator token publicly.
- Stop the pilot immediately if orders disappear after restart, operator access breaks, or the registry sees customer order contents.
