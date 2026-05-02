# P4P Online Proof

This document defines the public proof target for `v0.1`.

It is the proof-safe public story for the current repo state.

It is narrower than the full `dev` runtime and narrower than `PILOT-LIVE.md`.

The point is not to prove that the code is complex.

The point is to prove that direct restaurant-customer discovery and ordering can work without a platform middleman.

## Public Setup

The online proof should use separate public services:

- one public client
- one public primary registry
- one public backup registry
- one public demo restaurant node marked with `order_mode: "test"`

Use `demo-node/` for this proof.

Do not use `pilot-node/` for the public proof story or proof video.

`pilot-node/` belongs to the next gate: controlled live pilot preparation.

Example shape:

```text
client.p4p.example
registry-a.p4p.example
registry-b.p4p.example
demo-pizzeria.p4p.example/p4p
```

The important part is separation.

The client may discover through a registry, but menu and order must go directly to the node.

## Proof Flow

The proof video should show this sequence:

1. Open the public client.
2. Discover the demo restaurant through the primary registry.
3. Show that the node is marked as test-order only.
4. Show that the registry carries a signed node announcement.
5. Open the discovered menu and show that the request goes to the node endpoint.
6. Submit a test order and show that the order goes directly to the node.
7. Stop or block the primary registry.
8. Run discovery again.
9. Show that the client still discovers the node through the backup registry.
10. Show that menu and order still go directly to the node.

This proves:
- registry failover works for discovery
- node dual-registration keeps the restaurant discoverable
- registry is not an order relay
- menu and order remain node-owned
- the demo does not pretend to have approval from a real restaurant
- the node id has a signing key for announcement updates

## What The Proof Does Not Prove

`v0.1` does not prove:

- production security
- real restaurant operation
- restaurant approval for live orders
- CVR-backed restaurant verification
- online or protocol-managed payment
- delivery
- certification
- CVR binding
- module interoperability
- abuse resistance
- automatic registry synchronization

Those belong to later versions.

The proof is allowed to be narrow.

It should be honest about what it proves.

## Verification Note

If public hosting shows browser-only behavior, WAF filtering, or SSL differences, log that honestly.

Do not widen the public claim to hide runtime differences between curl, browser, and hosted infrastructure.

Use `docs/PROOF-STATUS.md` as the dated proof checkpoint log.

## Acceptance Checklist

Before calling `v0.1` launched:

- automated tests pass
- primary and backup registries are both reachable
- demo node appears in both registries
- demo node is marked `order_mode: "test"`
- demo node carries `node_public_key`, `signed_at`, and `signature`
- client can discover through primary
- client can discover through backup after primary fails
- menu request goes to the node, not the registry
- order request goes to the node, not the registry
- public proof wording matches README, `pizza4people.com`, the press kit, and the companion article
- current browser/curl hosting behavior is logged in `docs/PROOF-STATUS.md`
- any WAF or SSL differences are logged honestly
- proof video exists
- README or `docs/RELEASE-NOTES.md` links to the proof

When this checklist is complete, P4P is no longer only a local demo.

It is a public protocol proof.

The controlled live pilot remains a separate next gate under `PILOT-LIVE.md`.
