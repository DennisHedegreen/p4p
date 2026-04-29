# Node Implementer Kit

This is the short packet for people building independent P4P nodes.

The point is simple:

different implementations should be able to expose a menu, accept or reject orders, and announce themselves without depending on the reference node.

## Target For The First Interop Session

Each implementer should bring one node that can run locally, on a VPS, or behind a tunnel.

Minimum public node API:

- `GET /p4p/info`
- `GET /p4p/menu`
- `POST /p4p/order`

The node may be written in any stack.

It does not need to use the Python reference implementation.

## Required Behavior

### `GET /p4p/info`

`/info` is optional in the spec, but required for the first interop session because it makes testing easier.

Recommended response:

```json
{
  "node_id": "dk-test-node-001",
  "name": "Independent Test Node",
  "endpoint": "https://example.com/p4p",
  "open": true,
  "order_mode": "test",
  "protocol_version": "0.1"
}
```

Allowed `order_mode` values:

- `disabled`
- `menu_only`
- `test`
- `live`

For interop sessions, use `test` or `menu_only`.

Do not use `live` unless a real restaurant operator has explicitly approved live intake.

### `GET /p4p/menu`

Must return:

- `currency`
- `updated_at`
- `items`

Minimal valid menu:

```json
{
  "currency": "DKK",
  "updated_at": "2026-04-29T12:00:00Z",
  "items": [
    {
      "id": "kebab-box",
      "name": "Kebab Box",
      "description": "Test item",
      "price": 6500,
      "category": "kebab"
    }
  ]
}
```

Prices are integer minor units.

For DKK, `6500` means `65.00 DKK`.

### `POST /p4p/order`

Must accept this shape:

```json
{
  "customer_name": "P4P Interop Test",
  "customer_contact": "+4500000000",
  "fulfillment": "pickup",
  "items": [
    {"id": "kebab-box", "quantity": 1}
  ],
  "note": "Interop test order",
  "client_version": "p4p-node-checker-0.1"
}
```

If `order_mode` is `test`, the node should return an accepted test-order response.

If `order_mode` is `disabled` or `menu_only`, the node must reject the order.

Expected rejection:

```json
{
  "accepted": false,
  "reason": "orders_disabled",
  "message": "Orders are not enabled for this node."
}
```

Expected accepted test response:

```json
{
  "accepted": true,
  "order_id": "test-001",
  "estimated_ready": "2026-04-29T12:20:00Z",
  "message": "Test order received."
}
```

## Local Checker

Run this from the P4P repo:

```sh
python3 scripts/check-node.py --node-url http://127.0.0.1:8101/p4p
```

That checks:

- `/info`
- `/menu`
- basic schema shape
- safe order-mode metadata

It does not send an order by default.

To test order behavior:

```sh
python3 scripts/check-node.py --node-url http://127.0.0.1:8101/p4p --test-order
```

The checker will not send a test order to a node reporting `order_mode: "live"` unless this is explicit:

```sh
python3 scripts/check-node.py --node-url https://node.example.com/p4p --test-order --allow-live-order
```

## Shared Registry Test

After each node passes the local checker:

1. run one shared registry
2. each node announces to that registry
3. run the web client against the registry
4. verify that each node appears in discovery
5. fetch each menu directly
6. send one test order to each `test` node
7. switch one node to `menu_only` and verify orders are rejected

The important result is not that every node looks the same.

The important result is that independent nodes can satisfy the same protocol contract.

## Stop Conditions

Stop and fix the contract if:

- two conforming nodes need different clients
- a registry must know implementation-specific node details
- a node can only receive orders through a central relay
- a node says `menu_only` but still accepts orders
- a client has to trust registry-hosted menu or order data

Those failures mean the protocol boundary is leaking.
