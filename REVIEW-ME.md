# Review Me

This file is the fastest serious entrypoint for a second opinion on P4P.

It is not the full spec.

It is not the full architecture note.

It is not a request to read the whole repo from top to bottom.

## What P4P Claims Right Now

The current public claim is narrow:

a restaurant node can be discovered without a marketplace middleman owning first contact, while menu fetch and order submission go directly from client to node.

That is the `v0.1` public proof claim.

The next gate is a controlled live pilot.

## What P4P Is Not Claiming

P4P is not currently claiming:

- finished restaurant platform
- production security
- online payment
- delivery network
- registry-side order relay
- finished federation
- verified module marketplace

Payment modules are adapters only.

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

## If You Only Have 20 Minutes

Read in this order:

1. [`README.md`](README.md)
2. [`PROOF.md`](PROOF.md)
3. [`ARCHITECTURE.md`](ARCHITECTURE.md)
4. [`docs/PROOF-STATUS.md`](docs/PROOF-STATUS.md)
5. [`tests/test_v0_1_truthfulness.py`](tests/test_v0_1_truthfulness.py)

If you care more about wire-level correctness than product framing, swap step 3 for [`SPEC.md`](SPEC.md).

## What To Review

Please focus on these questions:

1. Is the public claim still narrower than the implementation horizon, or is the repo silently overclaiming?
2. Does discovery stay separate from ordering, or is the registry quietly becoming a middleman?
3. Is the payment boundary actually held, or are there places where P4P drifts toward payment-provider responsibility?
4. Do module and provider layers stay optional, or are they becoming hidden core requirements?
5. Is `pilot-node/` still honest as a next gate instead of being blurred into the current public proof?
6. Are the new hardware test lanes honest about what they are and are not?

## Useful Code Entry Points

If you want to inspect concrete runtime behavior instead of only prose:

- [`registry/`](registry/)
- [`demo-node/`](demo-node/)
- [`pilot-node/README.md`](pilot-node/README.md)
- [`pilot_node/routes.py`](pilot_node/routes.py)
- [`pilot_node/execution.py`](pilot_node/execution.py)
- [`pilot_node/hardware_lanes.py`](pilot_node/hardware_lanes.py)
- [`p4p_core/flow_contracts.py`](p4p_core/flow_contracts.py)

## Useful Commands

From the repo root:

```bash
./.venv/bin/python -m unittest tests.test_v0_1_truthfulness tests.test_dev_cleanup
./.venv/bin/python scripts/build_public_site.py
```

If you only want the pilot-node truth checks:

```bash
./.venv/bin/python -m unittest tests.test_v0_1_truthfulness
```

## What Kind Of Feedback Is Most Valuable

The most useful second opinion is not:

- "cool project"
- "you should add feature X"
- "have you considered making it a startup"

The most useful second opinion is:

- a concrete architectural objection
- a protocol ambiguity
- a hidden responsibility leak
- a claim that is broader than the evidence
- a test gap
- a simpler boundary that would make the system more honest

Issues, PR comments, or a short written critique are all fine.

Short and sharp is better than broad and polite.

## Current Truth About The Repo

The public story repo is intentionally more conservative than the fuller private development direction.

That is deliberate.

If something feels more mature in code than in the public claim, assume the public claim is the thing being protected unless the proof docs explicitly say otherwise.
