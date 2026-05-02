# P4P Community Modules

Status: public GitHub guide for people who want to build P4P-compatible modules.

P4P is an open protocol for direct restaurant discovery and ordering, with replaceable modules for payments, printing, delivery, POS, booking, and other operator-owned workflows.

P4P is the socket, not the appliances.

That means a restaurant or node operator should be able to choose which modules it runs.

It also means a module being published on GitHub does not automatically make it approved, trusted, production-ready, or part of P4P core.

## What A Module Is

A module is an optional capability around the small P4P core.

Good module examples:

- payment adapter
- printer or POS connector
- delivery adapter
- booking adapter
- accounting export
- stock or menu import
- trust or verification claim producer
- operator notification

These are not modules:

- registry announce
- registry heartbeat
- registry discover
- node identity
- node menu endpoint
- node order endpoint
- node order consent

If removing a module breaks basic discovery, menu fetch, or direct order submission, the module is too deep.

## Status Labels

Every public module should be labeled clearly in its manifest and documentation.

Use one of these public status families:

- `reference`: a P4P reference module or reference example
- `internal-mock`: an internal debug or test module
- `community`: a third-party or community module
- `experimental`: early work that may change
- `operator-local`: a restaurant or node-operator local module

Existing manifests may use more specific status strings such as `reference-example`, `internal-mock`, or `internal-mock-planned`.

The important rule is that readers can immediately tell whether a module is reference, mock/test, community, experimental, or local.

## Module Id Namespaces

The namespace must make ownership and trust boundaries visible.

- `p4p.*` is reserved for P4P core, reference, and internal test modules.
- `local.*` is for local development and operator experiments.
- community modules should use a namespace owned by the publisher.

Recommended community shapes:

```text
com.example.payment.stripe-adapter
dk.example.pos.kitchen-printer
org.example.delivery.bike-courier
```

Do not use `p4p.*` for a community module unless the module has been accepted as a P4P reference module.

Do not use underscores in `module_id`; the current schema allows lowercase letters, numbers, dots, and hyphens.

## Required Public Material

A useful module submission or external module repo should include:

- `provider.json` identifying who publishes it
- `module.json` describing what the module does
- a README that says whether it is reference, community, experimental, internal mock, or operator-local
- test instructions or a short test report
- data access summary
- required configuration
- failure modes
- whether it is public-facing, operator-only, trust-only, or observability-only

The manifest should follow:

- `docs/schemas/provider-manifest.schema.json`
- `docs/schemas/module-manifest.schema.json`

The deeper module model is described in:

- `docs/MODULE-RULES.md`
- `docs/MODULE-PROVIDERS.md`
- `docs/MODULE-EXECUTION-CONTRACT.md`

## Payment Module Boundary

P4P does not hold funds, process payments, store payment credentials, settle money, or act as merchant of record.

Payment modules are adapters chosen by the restaurant/operator.

A payment module may hand an order-scoped payment request to a provider or mark a local payment mode.

A payment module must not imply that P4P itself is the payment provider.

Do not market a module as `P4P Pay`.

Mock/test modules such as GodPay or ChaosPay must never be described as real money, real settlement, real wallets, crypto, redeemable value, or production payment systems.

Read `docs/PAYMENT-ADAPTER-STANDARD.md` before publishing any payment module.

## GitHub Contribution Path

For a module that belongs in this repo:

1. choose a module id and status label
2. add or update provider and module manifests
3. add a short README if the module needs explanation
4. document data access, configuration, and failure behavior
5. test locally against the reference runtime or explain why it is manifest-only
6. open a pull request with the status label visible in the title or description

For a module that should stay in its own repo:

1. publish the module repo with the same manifest shape
2. keep the module id outside `p4p.*`
3. document how a node operator can load or configure it
4. link it from discussion or docs only as a community module, not as verified P4P infrastructure

## What GitHub Means

GitHub is the place to share code, review manifests, test adapters, and build interoperable modules.

It is not a certification registry.

It is not a production module marketplace.

It is not proof that a payment, delivery, POS, or trust provider is safe for a real restaurant.

The P4P public profile should encourage module building while keeping trust labels visible.
