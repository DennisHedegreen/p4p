# P4P Release Notes

This file holds short checkpoint and release-candidate notes.

It is the place to point before cutting a proof-safe story to `main`.

## 2 May 2026 — Pilot Runtime Lane Checkpoint

Status:

- public-facing runtime checkpoint
- not a tag
- still not a broad production restaurant release

What changed:

- `p4p.stock.basic` is now executable inside `pilot-node`
- stock success emits `ORDER_VALIDATED` before the next lane
- configured unavailable items emit `ITEM_NOT_POSSIBLE -> ORDER_NEEDS_HUMAN` and do not continue to print
- `p4p.payment.cash` is now executable inside `pilot-node`
- pay-at-pickup success emits `PAYMENT_REQUIRED -> PAYMENT_MODE_CHANGED` before the next lane
- configured payment-mode failure emits `PAYMENT_FAILED -> ORDER_NEEDS_HUMAN` and does not continue to print
- stock, payment, and print now compose as a real local pilot flow

What this still does not imply:

- online payment
- card handling
- settlement
- third-party module marketplace
- production restaurant rollout

Verification:

- focused stock/payment/print tests passed
- full Python suite passed with 113 tests
- public audit passed
- JavaScript syntax check passed
- Python compile check passed

## 30 April 2026 — Dev Cleanup Checkpoint

Status:

- `dev` checkpoint only
- not merged to `main`
- not a tag
- not a public proof release by itself

What is now aligned:

- repo docs read as one narrow story: advanced prototype, public protocol proof now, controlled live pilot next
- `demo-node/` is explicitly proof-only
- `pilot-node/` is explicitly the only live-directed node surface
- `protocol_version` remains `0.1`
- `v0.2` module, provider, trust, and flow docs stay design layers instead of silent `v0.1` wire requirements
- `lab/.venv` and `pilot-node/.venv` are provisioned, and `registry/.venv` was repaired to include missing runtime dependencies
- the public-site generator, site data, press-kit HTML source, and companion article state are documented and linked back into the release gate

What is still missing before a proof-safe `main` cut:

- the hosted public surfaces are now back in sync in browser-visible copy, but the edge layer still returns Simply `455` on plain `curl`
- current browser/curl hosting behavior must stay logged in `docs/PROOF-STATUS.md`
- proof screenshots or the proof video must exist
- the next public story must be cut from a proof-safe subset of `dev`, not from a blind fast-forward

Branch reading:

- `dev` is the active integration line
- `main` stays conservative and showable
- `public-main` is a reference snapshot only, not a normal merge base

GitHub reading note:

- `dev` should now be pushed in smaller green checkpoints instead of waiting for another large silent cleanup
- when the repo meaning changes, `README.md` and the GitHub-facing explanation layer should move in the same pass as the code

## `v0.1.0-proof.1` Candidate

This candidate is not cut yet.

When it is ready, the release note should still describe a narrow proof:

- public client
- primary and backup registries
- public signed demo node in `order_mode=test`
- public site and press kit aligned with repo wording
- proof video or equivalent browser-verifiable record of registry failover plus direct node ordering

It must not imply:

- production security
- live restaurant approval
- online or protocol-managed payment
- delivery
- broad restaurant rollout
