# p4p.trust.cvr-basic

Status: `planned`

Status family: `planned`

Manifest: [`../../modules/p4p.trust.cvr-basic/module.json`](../../modules/p4p.trust.cvr-basic/module.json)

Provider: [`../../modules/p4p.trust.cvr-basic/provider.json`](../../modules/p4p.trust.cvr-basic/provider.json)

## Purpose

`p4p.trust.cvr-basic` is a planned trust module for Danish CVR-style identity claims.

It describes a future module that can connect declared node identity data to an external company lookup or signed trust claim.

## What It Would Do

- read public node identity claims
- look up declared CVR/company identifiers
- emit a signed or structured trust claim
- report match or missing-match outcomes

## What It Does Not Own

- node identity truth
- restaurant private keys
- registry discoverability
- payment
- order acceptance
- production verification policy

Trust claims are annotations. They must not replace node keys, root keys, delegations, or manifests.

## Data Access

Planned data:

- `declared_cvr_identifiers`
- `node_public_identity`

## Events

Inputs:

- `TRUST_CLAIM_REQUESTED`
- `NODE_IDENTITY_DECLARED`

Outputs:

- `TRUST_CLAIM_EMITTED`
- `CVR_MATCH_CONFIRMED`
- `CVR_MATCH_MISSING`

Failure mode:

- `CVR_MATCH_MISSING`

## Local Test Path

No executable reference path exists yet.

The manifest declares required configuration:

```text
cvr_lookup_source
```

## Current Readiness

This is placeholder trust-module material.

It is not a verified restaurant identity system.
