# pilot-node

Restaurant-owned node for the first controlled live pilot.

This is not the demo node.

It is also not the public proof node.

It is the smallest real node shape for one restaurant:

- persistent menu
- persistent orders
- operator-token protected controls
- signed announce
- signed heartbeat
- pickup orders
- pay at pickup
- optional stock validation lane
- optional pay-at-pickup payment-mode lane

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

The SQLite path is the pilot node's source of truth for menu, operator state, and order history.

Enable the small reference runtime lanes with `P4P_NODE_MODULES`:

- `p4p.stock.basic` emits `ORDER_VALIDATED`, or `ITEM_NOT_POSSIBLE` when a configured item is unavailable.
- `p4p.payment.cash` emits `PAYMENT_REQUIRED -> PAYMENT_MODE_CHANGED` for pay-at-pickup, or `PAYMENT_FAILED` when `P4P_PAYMENT_CASH_MODE=failed`.
- `p4p.order.print` emits the operator print/screen lane.

These lanes do not add online payment, card handling, or registry access to order contents.

Homebuilt or external module IDs can also be listed in `P4P_NODE_MODULES`.
If a module has no reference manifest, the pilot node keeps it as `undeclared_modules`
in operator state and does not execute or publish it as a P4P reference module.

External modules become declared only when the operator imports a local module manifest.
The first test path is `local.pizzacoin.wallet`, which remains outside `P4P/`.

Example local Pizzacoin payment selection:

```bash
P4P_NODE_MODULES=p4p.payment.cash,local.pizzacoin.wallet,p4p.order.print \
P4P_EXTERNAL_MODULE_MANIFESTS="../../Pizzacoin/contracts/module.json" \
P4P_PAYMENT_MODULE_ID=local.pizzacoin.wallet \
P4P_PAYMENT_EXTERNAL_CUSTOMER_USER_ID=usr_from_pizzacoin_gui \
./.venv/bin/uvicorn pilot_node:app --port 8201
```

In that mode the payment lane posts to the manifest `entrypoint`, auto-confirms
the fake payment by default, and emits `PAYMENT_REQUIRED -> PAYMENT_MODE_CHANGED`
or `PAYMENT_FAILED -> ORDER_NEEDS_HUMAN`.

The external HTTP payment executor is guarded:

- the selected module must be enabled in `P4P_NODE_MODULES`
- the module manifest must be imported with `P4P_EXTERNAL_MODULE_MANIFESTS`
- `P4P_PAYMENT_MODULE_ID` must name that imported module
- plain `http` entrypoints are accepted only on loopback hosts
- `P4P_PAYMENT_EXTERNAL_CUSTOMER_USER_ID` must be set for the fake wallet test

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
- `GET /p4p/info`

## Operator Endpoints

All operator endpoints require either:

- `Authorization: Bearer <token>`
- `X-P4P-Operator-Token: <token>`

Endpoints:

- `GET /operator/state`
- `PATCH /operator/state`
- `GET /operator/menu`
- `PUT /operator/menu`
- `GET /operator/orders`
- `GET /operator/orders/{order_id}/events`
- `PATCH /operator/orders/{order_id}`
- `POST /operator/reannounce`

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
