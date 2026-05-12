# P4P Provider Reference

Status: public GitHub reference for the current P4P provider manifests.

This directory explains the providers that currently appear behind the module manifests under `modules/`.

It is not a marketplace.

It is not a certification layer.

It is the human layer for provider identity, just as `docs/modules/` is the human layer for module behavior.

## One Page Per Provider

Every unique `provider_id` represented in the current reference manifest catalog should have exactly one human-readable page in this directory.

That page should answer:

- who publishes these modules?
- what kind of provider is it?
- which modules does it declare?
- which lanes does it claim to support?
- what status does the provider manifest actually carry?

## Current Providers

| Provider | Status | Current reading |
| --- | --- | --- |
| [`p4p.reference`](p4p.reference.md) | unsigned-reference | Reference provider for the current P4P example and mock modules. |

## Reading Rule

The provider page is the human explanation.

The provider manifest is the machine declaration.

For the planned provider model, read:

- [`../MODULE-PROVIDERS.md`](../MODULE-PROVIDERS.md)
- [`../COMMUNITY-MODULES.md`](../COMMUNITY-MODULES.md)
- [`../MODULE-EXECUTION-CONTRACT.md`](../MODULE-EXECUTION-CONTRACT.md)
