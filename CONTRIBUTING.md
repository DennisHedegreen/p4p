# Contributing To P4P

P4P is not being built as a generic app startup codebase.

It is a protocol proof plus a reference runtime that is trying to stay honest about what is core, what is optional, and what is still only design material.

## Read This First

If you are new to the repo, use this order:

1. `README.md`
2. `PROOF.md`
3. `SPEC.md`
4. `docs/GITHUB-READER-GUIDE.md`
5. `docs/README.md`

If you want implementation detail after that:

- `ARCHITECTURE.md`
- `docs/COMMUNITY-MODULES.md`
- `pilot-node/README.md`
- `TEST-GUIDE.md`
- `docs/MODULE-EXECUTION-CONTRACT.md`

## Branch Model

- `dev` is the active integration branch.
- `main` is the conservative public story branch.
- `public-main` is a reference snapshot only, not a normal merge base.

Do not assume the right move is to fast-forward `main` from `dev`.

Cut a smaller public story when the claim is ready.

## Push Cadence

Push more often than feels natural.

Default rule:

- if a meaningful checkpoint is green, push it to `dev`
- if a checkpoint changes what an outsider would think the repo is, update `README.md` or `docs/RELEASE-NOTES.md` in the same pass
- prefer two small named pushes over one large silent push later

The goal is that GitHub should explain the work as it moves, not only after a large cleanup.

## Public/Private Rule

GitHub visibility is repository-level.

That is why this project uses:

- public repo: `DennisHedegreen/p4p`
- private repo: `DennisHedegreen/p4p-dev`

Do not publish private branch history by accident.

Read `docs/PUBLIC-GITHUB.md` before cutting a public story.

## Before You Push

Run the green gate:

```sh
demo-node/.venv/bin/python -m unittest discover -s tests -v
bash scripts/public-audit.sh
node --check client/app.js
demo-node/.venv/bin/python -m compileall demo_node pilot_node registry p4p_core scripts lab
```

If the change is public-facing, also update the short explanation layer:

- `README.md`
- `docs/RELEASE-NOTES.md`
- `docs/PROOF-STATUS.md` when proof claims changed

## Contribution Stance

Good contributions make one of these clearer:

- the core protocol
- the node/registry reference runtime
- the controlled live-pilot path
- the module boundary between core and optional infrastructure

Bad contributions usually do one of these:

- widen the public claim without implementing the boundary
- turn `v0.2` design material into silent `v0.1` requirements
- make the runtime more magical instead of more inspectable

## Module Contributions

P4P should encourage modules without pretending every module is official, trusted, or production-ready.

Before proposing a module, read:

- `docs/COMMUNITY-MODULES.md`
- `docs/MODULE-RULES.md`
- `docs/MODULE-PROVIDERS.md`
- `docs/MODULE-EXECUTION-CONTRACT.md`
- `docs/PAYMENT-ADAPTER-STANDARD.md` for payment modules

Every module contribution must make these visible:

- module id and provider id
- public status label, such as `reference`, `internal-mock`, `community`, `experimental`, or `operator-local`
- whether it is executable, planned, manifest-only, or local-only
- data access
- required configuration
- failure modes
- test instructions or a short test report
- whether it is public-facing, operator-only, trust-only, or observability-only

Community modules should not use the `p4p.*` namespace.

Use `local.*` for local operator experiments.

Use a publisher-owned namespace for public community modules.

## Payment Module Contributions

P4P is not a payment provider.

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant/operator.

Payment module contributions must not:

- market themselves as `P4P Pay`
- imply that P4P handles settlement, refunds, chargebacks, or merchant-of-record duties
- describe a mock ledger, test wallet, or fake balance as real money
- describe an internal debug module as a real provider
- present test modules as production payment systems

If a module talks to a real payment provider, the module must say who owns the merchant relationship and which external provider handles payment, confirmation, settlement, refunds, and disputes.
