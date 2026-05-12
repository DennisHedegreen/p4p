# P4P

An open protocol for direct restaurant-customer discovery and ordering.

P4P is a phone book, not a marketplace.

P4P is the socket, not the appliances.

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant or node operator.

## What To Believe Right Now

- status: advanced prototype
- current public claim: public protocol proof for `v0.1`
- next gate: controlled live pilot
- public story: narrower than the full private `dev` runtime

The current proof is small on purpose:

1. a node announces itself to one or more registries
2. a client discovers the node through a registry
3. the client fetches the menu directly from the node
4. the client sends an order directly to the node
5. the client can fail over to a backup registry for discovery

After discovery, the registry is out of the loop.

## What Is Claimed In `v0.1`

The current public proof claims only that direct restaurant-customer discovery and ordering can work without a marketplace platform owning first contact.

That includes:

- registry discovery
- direct node menu fetch
- direct node order submission
- `order_mode` as explicit order consent
- client failover across registries
- a public demo node marked `order_mode: "test"`

`demo-node/` is the proof surface.

`pilot-node/` is not part of the current public proof claim. It is the next gate.

## What Exists In Prototype But Is Not The Public Claim

These layers exist in the repo as prototype support or future-direction work:

- signed node identity scaffolding beyond the minimum proof story
- optional root-signed delegation and manifest-based key lifecycle
- registry source export/import and mirror cache work
- moderated directory scaffolding
- signed trust-claim scaffolding
- module manifests, provider manifests, and pilot runtime lanes
- controlled live-pilot operator flows in `pilot-node/`

They are real prototype material.

They are not the same thing as the current public proof claim.

## What P4P Is Not Claiming Today

P4P is not currently claiming:

- broad production rollout
- production restaurant operations
- production security
- online payment
- delivery orchestration
- registry-side order relay
- customer account platform
- verified community module marketplace
- finished federation
- complete trust ecosystem

## Start Here

If you only want the current public claim:

1. `README.md`
2. `PROOF.md`
3. `docs/WHITEPAPER-v0.1.md`
4. `docs/PROOF-STATUS.md`

If you want the wire contract:

1. `SPEC.md`
2. `docs/README.md`
3. `docs/schemas/`
4. `docs/examples/`

If you want to give a second opinion without reading the whole repo:

1. `REVIEW-ME.md`
2. `README.md`
3. `PROOF.md`
4. `ARCHITECTURE.md`
5. `tests/test_v0_1_truthfulness.py`

If you want runtime architecture and anti-capture boundaries:

1. `ARCHITECTURE.md`
2. `registry/README.md`
3. `demo-node/README.md`

If you want the next gate after the proof:

1. `PILOT-LIVE.md`
2. `pilot-node/README.md`
3. `docs/FIVE-PLACE-PILOT-PACK.md`
4. `TEST-GUIDE.md`

If you want the module direction:

1. `docs/MODULES-START-HERE.md`
2. `docs/GITHUB-READER-GUIDE.md`
3. `docs/COMMUNITY-MODULES.md`
4. `docs/modules/README.md`
5. `docs/MODULE-EXECUTION-CONTRACT.md`
6. `modules/README.md`

## Canonical Document Roles

When documents overlap, read them like this:

- `README.md`: repo entrypoint and shortest public claim
- `PROOF.md`: canonical `v0.1` proof claim
- `docs/WHITEPAPER-v0.1.md`: explainer for humans before raw code
- `SPEC.md`: wire contract and normative rules
- `ARCHITECTURE.md`: service boundaries and anti-capture design
- `PILOT-LIVE.md`: separate next gate, not current proof
- `docs/GITHUB-READER-GUIDE.md`: reading-path routing
- `docs/PROOF-STATUS.md`: dated factual checkpoint log

If a statement is about what the protocol contract is, `SPEC.md` wins.

If a statement is about what the architecture should preserve, `ARCHITECTURE.md` wins.

If a statement is about what is publicly claimed right now, `PROOF.md` wins.

If a statement is about hosted or dated public proof facts, `docs/PROOF-STATUS.md` wins.

## Beyond `v0.1`

P4P is the first concrete vertical proof inside a broader `Protocols4People` direction.

That broader direction matters, but it is secondary to the current proof.

Read `docs/WHITEPAPER-v0.1.md` and `ARCHITECTURE.md` for the larger module, trust, and federation direction after the current proof boundary.
