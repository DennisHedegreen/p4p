# P4P GitHub Reader Guide

This file is for people who land on the GitHub repo and need the project to explain itself quickly.

## In One Sentence

P4P is an open protocol proof and reference runtime for direct restaurant-customer discovery and ordering without a platform owning the first-contact layer.

## What To Believe Right Now

Believe this:

- advanced prototype
- real code, real tests, real runtime split
- public protocol proof now
- controlled live pilot next

Do not believe this:

- broad production rollout
- finished payment stack
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

1. `docs/MODULE-PROVIDERS.md`
2. `docs/MODULE-EXECUTION-CONTRACT.md`
3. `docs/FIRST-FLOWS.md`
4. `modules/`

## Repo Shape

The repo has three important layers:

- core protocol and runtime: `registry/`, `demo-node/`, `pilot-node/`, `client/`, `p4p_core/`
- contract and explanation layer: `SPEC.md`, `ARCHITECTURE.md`, `docs/`
- proof and release discipline: `PROOF.md`, `PILOT-LIVE.md`, `TEST-GUIDE.md`, `docs/RELEASE-NOTES.md`

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
- is local or node-owned state staying primary?
- does the runtime become more inspectable rather than more magical?
