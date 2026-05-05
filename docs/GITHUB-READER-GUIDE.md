# P4P GitHub Reader Guide

This file is for people who land on the GitHub repo and need the project to explain itself quickly.

## In One Sentence

P4P is an open protocol for direct restaurant discovery and ordering, with replaceable modules for payments, printing, delivery, POS, booking, and other operator-owned workflows.

## What To Believe Right Now

Believe this:

- advanced prototype
- real code, real tests, real runtime split
- public protocol proof now
- controlled live pilot next

Do not believe this:

- broad production rollout
- finished payment stack
- P4P as a payment provider
- verified community module marketplace
- delivery network
- complete trust ecosystem
- full federation finished as stable product

## Fast Reading Path

If you only want the public story:

1. `README.md`
2. `PROOF.md`
3. `docs/PROOF-STATUS.md`
4. `docs/RELEASE-NOTES.md`

If you want the protocol:

1. `SPEC.md`
2. `docs/README.md`
3. `docs/schemas/`
4. `docs/examples/`

If you want the runtime architecture:

1. `ARCHITECTURE.md`
2. `registry/README.md`
3. `demo-node/README.md`
4. `pilot-node/README.md`

If you want the module direction:

1. `docs/COMMUNITY-MODULES.md`
2. `docs/modules/README.md`
3. `docs/MODULE-PROVIDERS.md`
4. `docs/MODULE-EXECUTION-CONTRACT.md`
5. `docs/FIRST-FLOWS.md`
6. `docs/MODULE-RULES.md`
7. `modules/README.md`

If you want to build a module:

1. `docs/COMMUNITY-MODULES.md`
2. `docs/modules/README.md`
3. `docs/MODULE-RULES.md`
4. `docs/MODULE-PROVIDERS.md`
5. `docs/MODULE-EXECUTION-CONTRACT.md`
6. `modules/README.md`

## Repo Shape

The repo has four important layers:

- core protocol and runtime: `registry/`, `demo-node/`, `pilot-node/`, `client/`, `p4p_core/`
- contract and explanation layer: `SPEC.md`, `ARCHITECTURE.md`, `docs/`
- module reference layer: `modules/`, provider manifests, module manifests, and module execution docs
- proof and release discipline: `PROOF.md`, `PILOT-LIVE.md`, `TEST-GUIDE.md`, `docs/RELEASE-NOTES.md`

## Module Builder Map

Core protocol is the small direct loop: registry discovery, node identity, node menu, node order, and order-consent state.

`pilot-node/` is the controlled live-pilot foundation and the current place where operator-owned module execution is tested.

`registry/` lists what nodes announce. It does not certify which modules are trusted.

Provider manifests identify who publishes a module.

Module manifests describe what a capability does, what data it needs, and how it reports results.

`docs/modules/` explains each current reference, planned, and internal mock module in ordinary language before you inspect the raw JSON manifests.

External modules may live in their own repositories, but they should still follow the same manifest and status-label rules.

Payment modules are adapters only. P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

## Branch And Repo Reality

This project is intentionally split across:

- private integration repo: `DennisHedegreen/p4p-dev`
- public story repo: `DennisHedegreen/p4p`

`dev` moves first.

`main` should stay easier to show and easier to explain.

That means GitHub may sometimes lag the private integration branch on purpose, but when it does, the public repo should still explain what it is missing and why.

## If You Review The Code

The main questions are:

- is the core still small?
- is the public claim still narrower than the implementation horizon?
- are modules staying optional instead of becoming hidden requirements?
- are community modules clearly labeled instead of silently treated as official?
- are payment modules kept as adapters instead of becoming P4P as payment provider?
- is local or node-owned state staying primary?
- does the runtime become more inspectable rather than more magical?
