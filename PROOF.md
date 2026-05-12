# P4P Online Proof

This document defines the current public proof claim for `v0.1`.

It is narrower than the full prototype runtime and narrower than `PILOT-LIVE.md`.

If documents overlap:

- `PROOF.md` wins on what is publicly claimed right now
- `docs/PROOF-STATUS.md` wins on dated hosted-proof facts
- `SPEC.md` wins on wire contract details

## The Current Public Claim

P4P currently claims one thing:

a restaurant node can be discovered without a marketplace middleman owning first contact, while menu fetch and order submission go directly from client to node.

The current public proof is intentionally small:

1. a node announces itself to one or more registries
2. a client discovers the node through a registry
3. the client fetches the menu directly from the node
4. the client sends an order directly to the node
5. the client fails over to a backup registry if the primary disappears

The registry must not become an order relay.

The proof must stay honest enough that a skeptical technical reader can tell exactly what is being shown.

## What Is Part Of The Proof

The current proof includes:

- one public client
- one public primary registry
- one public backup registry
- one public demo node marked `order_mode: "test"`
- direct node menu fetch
- direct node order submission
- client-side registry failover

The proof may also show that the demo node carries a signing key for its announcement updates.

That is acceptable as part of the current proof story.

It is not the same thing as claiming a finished trust or certification system.

## What Exists In Prototype But Is Not Required By The Proof

The repo also contains real prototype support layers that are not the core of the current proof claim:

- optional root-signed delegation
- manifest-based key lifecycle
- registry source export/import and mirror cache work
- moderated directory scaffolding
- signed trust-claim scaffolding
- pilot-node operator/runtime lanes
- module/provider manifest catalogs beyond the minimum proof loop

These may be mentioned as implemented prototype layers.

They must not be mistaken for the main thing the public proof is trying to establish.

## Public Setup

The proof should use separate public services:

- one public client
- one public primary registry
- one public backup registry
- one public demo restaurant node marked with `order_mode: "test"`

Use `demo-node/` for this proof.

Do not use `pilot-node/` for the public proof story or proof video.

`pilot-node/` belongs to the next gate: controlled live pilot preparation under `PILOT-LIVE.md`.

Example shape:

```text
client.p4p.example
registry-a.p4p.example
registry-b.p4p.example
demo-pizzeria.p4p.example/p4p
```

The important part is separation.

After discovery, menu and order must go directly to the node.

## Proof Flow

The proof video or equivalent hosted proof artifact should show this sequence:

1. Open the public client.
2. Discover the demo restaurant through the primary registry.
3. Show that the node is marked as test-order only.
4. Show that the menu request goes to the node endpoint.
5. Submit a test order and show that the order goes directly to the node.
6. Stop or block the primary registry.
7. Run discovery again.
8. Show that the client still discovers the node through the backup registry.
9. Show that menu and order still go directly to the node.

This proves:

- registry failover works for discovery
- node dual-registration keeps the restaurant discoverable
- the registry is not an order relay
- menu and order remain node-owned
- the demo does not pretend to be a real restaurant pilot

## What The Proof Does Not Prove

`v0.1` does not prove:

- production security
- real restaurant operation
- restaurant approval for live orders
- online or protocol-managed payment
- delivery
- registry-side order storage
- certification
- finished federation
- module interoperability as a mature ecosystem
- complete trust or abuse-resistance layers

Those belong to later gates.

The next gate is the controlled live pilot in `PILOT-LIVE.md`.

## Verification Note

If public hosting shows browser-only behavior, WAF filtering, or SSL differences, log that honestly.

Do not widen the public claim to hide runtime differences between curl, browser, and hosted infrastructure.

Use `docs/PROOF-STATUS.md` as the dated proof checkpoint log.

## Acceptance Checklist

Before calling `v0.1` launched as a public proof:

- automated tests pass
- primary and backup registries are both reachable
- demo node appears in both registries
- demo node is marked `order_mode: "test"`
- client can discover through primary
- client can discover through backup after primary fails
- menu request goes to the node, not the registry
- order request goes to the node, not the registry
- public proof wording matches `README.md`, the public site, and the press framing
- current browser/curl hosting behavior is logged in `docs/PROOF-STATUS.md`
- any WAF or SSL differences are logged honestly
- proof video or equivalent proof artifact exists

When this checklist is complete, P4P is no longer only a local demo.

It is a public protocol proof.

The controlled live pilot remains a separate next gate.
