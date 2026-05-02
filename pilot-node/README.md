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
- optional pay-at-pickup payment-mode lane
- optional kitchen-screen operator surface
- optional customer order-status surface

Start it in `menu_only`.

Move to `live` only through explicit operator action.

## Local Run

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
P4P_PILOT_NODE_DB_PATH=/tmp/p4p-pilot-node.sqlite3 \
P4P_OPERATOR_TOKEN=change-this \
P4P_REGISTRY_URLS=http://127.0.0.1:8000,http://127.0.0.1:8002 \
P4P_NODE_BASE_URL=http://127.0.0.1:8201 \
P4P_NODE_ORDER_MODE=menu_only \
./.venv/bin/uvicorn pilot_node:app --port 8201
```

The SQLite path is the pilot node's source of truth for menu, operator state,
active payment-module selection, and order history.

Enable the small reference runtime lanes with `P4P_NODE_MODULES`:

- `p4p.catalog.editor` exposes the built-in operator catalog editor for item ids, prices, categories, and active availability.
- `p4p.stock.basic` emits `ORDER_VALIDATED`, or `ITEM_NOT_POSSIBLE` when a configured item is unavailable.
- `p4p.customer.status` exposes read-only public order status without customer contact details, notes, or operator event logs.
- `p4p.kitchen.screen` exposes the built-in operator order queue for kitchen status updates.
- `p4p.payment.cash` emits `PAYMENT_REQUIRED -> PAYMENT_MODE_CHANGED` for pay-at-pickup, or `PAYMENT_FAILED` when `P4P_PAYMENT_CASH_MODE=failed`.
- `p4p.payment.godpay-mock` emits a random internal test payment success/failure based on `P4P_GODPAY_SUCCESS_THRESHOLD`.
- `p4p.payment.chaospay-mock` is declared as a planned internal chaos-payment mock, but its scenario executor is intentionally not enabled yet.
- `p4p.order.print` emits the operator print/screen lane.

These lanes do not add online payment, card handling, real wallet handling, settlement, or registry access to order contents.

Homebuilt or external module IDs can also be listed in `P4P_NODE_MODULES`.
If a module has no reference manifest, the pilot node keeps it as `undeclared_modules`
in operator state and does not execute or publish it as a P4P reference module.

External modules become declared only when the operator imports a local module manifest.
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
- `POST /p4p/order`
- `GET /p4p/orders/{order_id}`
- `GET /p4p/orders/{order_id}/status`
- `GET /p4p/info`

## Operator Endpoints

All operator endpoints require either:

- `Authorization: Bearer <token>`
- `X-P4P-Operator-Token: <token>`

Endpoints:

- `GET /operator`
- `GET /operator/state`
- `PATCH /operator/state`
- `GET /operator/modules`
- `PATCH /operator/modules/payment`
- `GET /operator/menu`
- `PUT /operator/menu`
- `GET /operator/orders`
- `GET /operator/orders/{order_id}/events`
- `PATCH /operator/orders/{order_id}`
- `POST /operator/reannounce`

`GET /operator` serves the local browser dashboard. The HTML shell is readable
without a token, but all operator data requests still require the operator token.

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
