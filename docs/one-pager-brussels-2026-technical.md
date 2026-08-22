# Pizza4People / P4P

*Brussels 2026 hackathon one-pager - technical version*

Use this when the group needs the deeper technical version.

## Technical claim the group can stand behind

P4P is a direct-ordering protocol proof where discovery goes through a registry,
but menu and order traffic go directly from client to node.

The registry must not become an order relay.

## Why it is technically interesting

Most food-ordering systems collapse discovery, customer contact, menu truth,
operator tooling, and payment surface into one platform.

P4P splits those layers on purpose.

- discovery can be public
- node endpoint stays shop-owned
- menu is fetched from the node
- orders are submitted to the node
- payment is outside core
- modules stay outside the minimum proof loop

## Core wire loop

`announce -> heartbeat -> discover -> menu -> order`

More explicitly:

1. node announces itself to one or more registries
2. node sends heartbeats so stale entries disappear
3. client queries registry for nearby nodes
4. client fetches menu directly from node endpoint
5. client submits order directly to node endpoint
6. client can fail over to a backup registry for discovery

## Request path proof

- `discover`: `client -> registry`
- `menu`: `client -> node`
- `order`: `client -> node`
- `failover`: `client -> backup registry`

After discovery, the registry is out of the loop.

## Technical version the group can show

- one small registry
- one small shop node
- one browser client
- one operator screen
- explicit `order_mode`
- visible request trace that proves menu/order hit the node, not the registry
- optional backup registry if the team has time

## Hackathon-safe boundary

In the hackathon we are **not** claiming:

- production security
- online payment
- delivery logistics
- restaurant rollout
- mature federation
- full trust/certification system

The honest hackathon claim is smaller:

**a direct pickup-ordering path can work without a marketplace owning first
contact**

## Anti-capture boundary

This is not "Uber Eats but open source."

The point is not just to rebuild a food app stack.

The point is to keep the minimum interoperable core small enough that:

- a shop can remain directly reachable
- a registry can help discovery without owning the customer relationship
- modules can compete above the core instead of replacing it

## Technical material already there

- owner-facing concept surface: `pizza4people.com`
- repo: `github.com/DennisHedegreen/p4p`
- public proof boundary: `PROOF.md`
- wire contract: `SPEC.md`
- wider explainer: `docs/WHITEPAPER-v0.1.md`

## Why this matters beyond the hackathon

If the demo works, it is more than a nice ordering mockup.

It becomes a proof that the discovery layer and the ordering layer do not have
to be owned by the same platform.
