# P4P GitHub Reader Guide

This file routes readers to the right P4P document in the right order.

It is a reading-path document, not the public proof claim, not the protocol spec, and not the proof checkpoint log.

## In One Sentence

P4P is an open protocol for direct restaurant discovery and ordering, with replaceable modules and operator-owned workflows around a small core.

## What To Believe Right Now

Believe this:

- advanced prototype
- public protocol proof for `v0.1`
- controlled live pilot next
- real code, real tests, real runtime split

Do not believe this:

- broad production rollout
- finished payment stack
- P4P as a payment provider
- verified community module marketplace
- delivery network
- complete trust ecosystem
- full federation finished as stable product

## Canonical Sources

When documents overlap, read them like this:

- `README.md`: repo entrypoint and shortest public claim
- `PROOF.md`: canonical current public proof claim
- `docs/WHITEPAPER-v0.1.md`: explainer and boundary document
- `SPEC.md`: wire contract and normative rules
- `ARCHITECTURE.md`: architecture and anti-capture boundary
- `PILOT-LIVE.md`: separate next gate
- `docs/PROOF-STATUS.md`: dated proof checkpoint log

## Fast Reading Paths

If you only want the public story:

1. `README.md`
2. `PROOF.md`
3. `docs/WHITEPAPER-v0.1.md`
4. `docs/PROOF-STATUS.md`
5. `docs/RELEASE-NOTES.md`

If you want the protocol:

1. `SPEC.md`
2. `docs/README.md`
3. `docs/schemas/`
4. `docs/examples/`

If you want the runtime architecture:

1. `ARCHITECTURE.md`
2. `registry/README.md`
3. `demo-node/README.md`

If you want to review the repo without reading everything:

1. `REVIEW-ME.md`
2. `README.md`
3. `PROOF.md`
4. `ARCHITECTURE.md`
5. `tests/test_v0_1_truthfulness.py`

If you want the live-pilot boundary:

1. `PILOT-LIVE.md`
2. `pilot-node/README.md`
3. `TEST-GUIDE.md`

If you want the module direction:

1. `docs/MODULES-START-HERE.md`
2. `docs/COMMUNITY-MODULES.md`
3. `docs/modules/README.md`
4. `docs/providers/README.md`
5. `docs/MODULE-PROVIDERS.md`
6. `docs/MODULE-EXECUTION-CONTRACT.md`
7. `docs/FIRST-FLOWS.md`
8. `docs/MODULE-RULES.md`
9. `modules/README.md`

Every current reference manifest should also have its own human-readable page under `docs/modules/`.

Every unique current provider identity should also have its own human-readable page under `docs/providers/`.

If you want to build a module:

1. `docs/COMMUNITY-MODULES.md`
2. `docs/modules/README.md`
3. `docs/MODULE-RULES.md`
4. `docs/MODULE-PROVIDERS.md`
5. `docs/MODULE-EXECUTION-CONTRACT.md`
6. `modules/README.md`

## Repo Shape

The repo has four important layers:

- core protocol and reference runtime: `registry/`, `demo-node/`, `client/`, `p4p_core/`
- live-pilot foundation: `pilot-node/`
- contract and explanation layer: `SPEC.md`, `ARCHITECTURE.md`, `docs/`
- proof and release discipline: `PROOF.md`, `PILOT-LIVE.md`, `TEST-GUIDE.md`, `docs/PROOF-STATUS.md`, `docs/RELEASE-NOTES.md`

## Reading Notes

`demo-node/` belongs to the public proof.

`pilot-node/` belongs to the controlled live-pilot path.

`registry/` lists what nodes announce. It does not become an order relay, payment owner, or hidden certification authority.

Payment modules are adapters only. P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Community modules may exist without becoming automatically approved.

## Branch And Repo Reality

This project is intentionally split across:

- private integration repo: `DennisHedegreen/p4p-dev`
- public story repo: `DennisHedegreen/p4p`

`dev` moves first.

`main` should stay easier to show and easier to explain.

That means GitHub may sometimes lag the private integration branch on purpose, but the public repo should still explain what is missing and why.

## If You Review The Code

The main questions are:

- is the core still small?
- is the public claim still narrower than the implementation horizon?
- are modules staying optional instead of becoming hidden requirements?
- are community modules clearly labeled instead of silently treated as official?
- are payment modules kept as adapters instead of becoming P4P as payment provider?
- is node-owned state staying primary after discovery?
- does the runtime stay inspectable instead of becoming magical?
