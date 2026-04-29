# P4P Release Plan

This document separates protocol versioning from repo releases.

The active wire contract is still `protocol_version: "0.1"`.

Repo releases are alpha milestones that make the work publishable in a controlled order.

## Branches

`main` is the stable story branch.

Use it for states that can be shown without explaining unfinished internal work.

`dev` is the active integration branch.

Use it for fast protocol, reference implementation, and documentation work.

Feature branches are optional and should only be used for risky or conflicting changes.

Because `dev` may be ahead of the release story, do not fast-forward `main` from `dev` unless the whole current `dev` state is ready to become the next public story.

When pacing matters, create a short release branch or cherry-pick the specific milestone commits into `main`.

## Release Milestones

### `v0.1.0-alpha.1` - Local Protocol Proof

Stable local proof of the base loop:

- registry
- demo node
- web client
- direct menu fetch
- direct test order
- client failover across dual-registered registries

This can be tagged from the initial proof state.

### `v0.1.0-alpha.2` - Operator And Signed Node

Adds the first serious control and trust layers:

- order consent with `disabled`, `menu_only`, `test`, and `live`
- demo-only node operator surface
- signed node announcements
- signed heartbeats
- client labels for signed nodes

This is still not production security.

It proves node-key control, not restaurant certification.

### `v0.1.0-alpha.3` - Identity Log Skeleton

Adds the first registry-side identity-history layer:

- append-only signed node identity events
- read-only identity-log inspection
- no node private keys stored in registry
- tests proving signed announcements are logged and tampered updates are rejected

Registry-signed snapshots remain later unless needed for the online proof.

### `v0.1.0-alpha.4` - Module And Provider Manifests

Adds a document-first module/provider contract:

- module manifest examples
- provider manifest examples
- provider public signing keys
- data-access declarations
- client display only, no module execution requirement

The registry still lists what nodes announce.

It does not certify modules.

### `v0.1.0-proof.1` - Public Online Proof

First public proof deployment:

- one public client
- one public primary registry
- one public backup registry
- one public signed demo node
- HTTPS in front of public endpoints
- demo node marked as test-order only
- proof video showing primary-registry failure and backup discovery

This is the first release that should be easy to explain to people outside the repo.

## Main Merge Rule

A milestone can move to `main` only when:

- the milestone has a short release note
- existing tests pass
- `PROOF.md`, `ROADMAP.md`, or this file reflects the current claim
- the release does not imply production security, live restaurant approval, payment, delivery, or CVR verification unless those are actually implemented

Do not merge an impressive demo to `main` if its claim is unclear.

Clarity is part of the release.

## Tag Rule

Use Git tags only for states that can be named and explained.

Recommended pattern:

- `v0.1.0-alpha.1`
- `v0.1.0-alpha.2`
- `v0.1.0-alpha.3`
- `v0.1.0-alpha.4`
- `v0.1.0-proof.1`

The `v0.1.0` final tag should wait until the public proof is recorded and the docs clearly distinguish proof from production.

## Current Default

Keep building on `dev`.

Keep `main` conservative.

Use staged release tags to make the next weeks look deliberate, even if much of the work was built quickly.
