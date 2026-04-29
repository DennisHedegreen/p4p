# pilot-node

Restaurant-owned node for the first controlled live pilot.

This is not the demo node.

It is the smallest real node shape for one restaurant:

- persistent menu
- persistent orders
- operator-token protected controls
- signed announce
- signed heartbeat
- pickup orders
- pay at pickup

## Local Run

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
P4P_PILOT_NODE_DB_PATH=/tmp/p4p-pilot-node.sqlite3 \
P4P_OPERATOR_TOKEN=change-this \
P4P_REGISTRY_URLS=http://127.0.0.1:8000,http://127.0.0.1:8002 \
P4P_NODE_BASE_URL=http://127.0.0.1:8201 \
./.venv/bin/uvicorn pilot_node:app --port 8201
```

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
- `PATCH /operator/orders/{order_id}`
- `POST /operator/reannounce`

## Pilot Rules

- Use `order_mode=menu_only` until the restaurant is ready.
- Use `order_mode=live` only after the operator has confirmed readiness.
- Use pickup and pay at pickup for the first pilot.
- Do not expose the operator token publicly.
