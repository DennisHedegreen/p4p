# P4P Node Operator Lite

Node Operator Lite is the first reference control surface for a restaurant-owned node.

It is not a registry feature.

It is not a protocol module.

It is an implementation-specific admin layer that lives with the node.

## Current Scope

The reference demo node exposes:

- `GET /operator`
- `GET /operator/state`
- `POST /operator/state`
- `POST /operator/reannounce`

The operator can currently control:

- node open or closed state
- `order_mode`
- active module ids
- reannounce to configured registries
- registry health visibility

This is enough to prove that a restaurant/node operator can change what the node announces without asking a registry for permission.

## Boundary Rule

The registry may store and return the latest announced node metadata.

The registry must not own the operator surface.

The operator controls node state.

The registry lists node state.

## Security Status

This reference operator is demo-only.

It has no authentication or authorization.

Do not expose it on the public internet as-is.

For public deployment, place it behind private network access, authentication, or a separate secure admin layer.

## Later Direction

A production node operator should eventually manage:

- menu edits
- live order activation
- order queue and readiness state
- module provider credentials
- node keys and signed manifests
- restaurant verification claims
- backup-node configuration

Those can evolve without moving restaurant control into the registry.
