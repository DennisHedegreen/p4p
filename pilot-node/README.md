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

## Order States

The first pilot order-state set is:

- `new`
- `accepted`
- `rejected`
- `ready`
- `completed`
- `cancelled`

## Public Endpoints

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
