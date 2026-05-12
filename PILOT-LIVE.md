# P4P Live Pilot

This document defines the first real restaurant pilot.

It is not a demo-node proof.

It is a controlled live pilot with one real restaurant, pickup orders, and direct client-to-node order flow.

The public proof and the live pilot are separate gates.

`demo-node/` belongs to the public proof.

`pilot-node/` belongs to this pilot document.

This file is the next gate after the current public proof.

It is not part of the current `v0.1` proof claim.

## 1. Pilot Goal

The pilot should prove one thing:

a real customer can discover a real restaurant without a platform middleman, fetch the menu directly from the restaurant node, and send a pickup order directly to that node.

The registry must not receive:

- basket contents
- customer name
- customer phone number
- order notes
- payment information

The restaurant node owns that data.

## 2. Topology

First live topology:

- `client.pizza4people.com`
  Public browser client.
- `registry-a.pizza4people.com`
  Primary registry, likely on Hetzner.
- `registry-b.pizza4people.com`
  Backup registry, on Dennis' own server.
- restaurant node
  The restaurant-owned or restaurant-controlled node.

The restaurant node may initially be hosted for the restaurant if necessary.

If it is hosted by Dennis during the first pilot, document it honestly as a hosted restaurant node.

The architectural rule still holds:

`Client -> Registry`

for discovery only.

After discovery:

`Client -> Restaurant Node`

for menu and order.

## 3. Pilot Scope

Allowed in `pilot.1`:

- one restaurant
- pickup only
- pay at pickup
- live orders only after explicit operator activation
- signed node announce
- signed node heartbeat
- primary and backup registry announcement
- persistent menu
- persistent order history
- operator login via token-protected operator surface
- operator order dashboard
- order status updates

Not allowed in `pilot.1`:

- delivery
- online payment
- user accounts
- reviews
- loyalty
- platform-hosted customer profiles
- central order relay
- registry-side order storage
- broad trust/federation claims

## 4. Ownership

Registry owns:

- public node metadata
- last seen
- discovery results
- public signed identity events

Restaurant node owns:

- menu
- orders
- customer contact
- operator controls
- node key material
- live/test/menu-only state

Client owns:

- temporary form state
- selected registry list
- selected node state

## 5. Stop Conditions

Stop the pilot if:

- restaurant cannot see new orders
- duplicate orders cannot be distinguished
- customer contact reaches the registry
- orders disappear after node restart
- operator login is exposed or broken
- live/test/menu-only state is unclear
- restaurant cannot turn ordering off quickly
- backup registry cannot discover the node after primary failure
- customer-facing client sends orders to anything except the restaurant node

## 6. Minimum Pilot Node

The first restaurant node must have:

- SQLite-backed menu
- SQLite-backed orders
- public `GET /p4p/menu`
- public `POST /p4p/order`
- private `GET /operator/state`
- private `PATCH /operator/state`
- private `GET /operator/orders`
- private `PATCH /operator/orders/{order_id}`
- private `GET /operator/menu`
- private `PUT /operator/menu`
- signed announce to all configured registries
- signed heartbeat to all configured registries
- `order_mode`: `disabled`, `menu_only`, `test`, or `live`

Operator endpoints must require an operator token.

The pilot node should complete a local SQLite-backed dry run before public DNS, HTTPS, or restaurant onboarding is treated as ready.

## 7. Launch Checklist

Before the restaurant goes live:

- pilot-node has passed the local dry run in `TEST-GUIDE.md`
- public HTTPS works for client, both registries, and restaurant node
- node announces to both registries
- both registries discover the node
- direct menu fetch works from the public client
- direct order POST works against the restaurant node
- orders persist after node restart
- operator login works
- restaurant can accept, reject, mark ready, complete, and cancel orders
- restaurant can inspect operator order events if a module lane escalates or becomes uncertain
- restaurant can set `order_mode=menu_only` quickly
- restaurant can set `open=false` quickly
- primary registry can be stopped and backup discovery still works
- customer-facing text says pickup and pay at pickup
- no demo wording appears on the live restaurant surface

## 8. What The Pilot Proves

The pilot proves:

- direct restaurant discovery can work without a marketplace platform
- a restaurant node can hold its own operational data
- orders can go directly from client to restaurant node
- registry failover can preserve discovery
- the public protocol boundary can survive a real order flow

## 9. What The Pilot Does Not Prove

The pilot does not prove:

- production-scale abuse resistance
- trusted federation
- CVR-backed verification
- payment module readiness
- delivery module readiness
- multi-restaurant operations
- independent implementation compatibility
- long-term governance

Those belong to later gates in `ROADMAP.md`.
