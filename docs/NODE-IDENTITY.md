# P4P Node Identity

Node identity is the first cryptographic ownership layer.

It proves that the same node key controls future updates to one `node_id`.

It does not prove that the node belongs to a real restaurant.

Restaurant verification belongs in later trust claims, CVR checks, and signed attestations.

## Key Model

A node has an Ed25519 keypair:

- private key stays with the node/operator
- public key is announced to registries

This is the operational node key.

An optional second layer may exist above it:

- a root identity key
- one or more delegated operational node keys

In that model, the root key authorizes a specific operational key for a specific `node_id`.

There should be no P4P server that holds every node private key.

A server only has private keys for nodes it actually hosts.

Registries store public signed announcements.

They do not need node private keys to verify those announcements.

The public key format is:

```text
ed25519:<base64url-raw-public-key>
```

The private key uses the same prefix internally:

```text
ed25519:<base64url-raw-private-key>
```

## Signed Announcements

When a node announces itself, it signs the node metadata without the `signature` field.

The signed fields include:

- node metadata
- `node_public_key`
- `signed_at`

The announcement then carries:

```json
{
  "node_public_key": "ed25519:...",
  "signed_at": "2026-04-30T18:00:00Z",
  "signature": "ed25519:..."
}
```

The registry verifies the signature before storing a signed announcement.

For a signed `node_id`, `signed_at` must be an RFC 3339 timestamp with timezone and must be strictly newer than the last accepted signed event for that `node_id` at that registry.

## Root Delegation Skeleton

The current next-step skeleton adds an optional root-signed delegation.

That delegation says, in effect:

- this root identity authorizes this operational node key
- for this `node_id`
- with this role
- and these protocol capabilities

Current delegation fields:

- `root_public_key`
- `issued_at`
- optional `expires_at`
- `role`: `primary` or `backup`
- `capabilities`: currently `announce` and/or `heartbeat`
- `signature`

The root signs a payload containing:

- `node_id`
- `node_public_key`
- `root_public_key`
- `issued_at`
- optional `expires_at`
- `role`
- `capabilities`

The operational node key still signs the full node announcement.

The registry verifies both signatures when delegation is present.

## Protected Updates

When a registry already knows a signed `node_id`, later updates must be signed by the same public key.

The registry rejects:

- unsigned updates to a signed node id
- updates with a different public key
- updates where the metadata no longer matches the signature
- older signed replays once the registry has already accepted a newer signed event for that node id

If a node id is already known with root delegation, the registry also rejects:

- later announcements that drop delegation entirely
- later delegated announcements with a different `root_public_key`

If the registry also has a current root-signed node manifest for that `node_id`, the registry further requires that:

- the delegated `root_public_key` matches the current manifest
- the operational node key appears in the current manifest
- the manifest entry is still `active`
- the manifest entry still allows the required capability

This prevents a simple JSON spoof from taking over an existing node announcement.

## Signed Heartbeats

Signed nodes also send signed heartbeats.

The signed heartbeat fields are:

- `node_id`
- `open`
- `signed_at`

This prevents an unsigned heartbeat from toggling a signed node open or closed.

The same monotonic rule applies here: a signed heartbeat must be newer than the last accepted signed event for that node id at that registry.

If the stored node has root delegation, the registry also checks that:

- the delegation is still active
- the delegation has not expired
- `heartbeat` is included in delegated capabilities

If the registry also has a current node manifest, the same stored operational key must still match an active manifest entry that allows `heartbeat`.

## Node Manifest And Root Rotation Skeleton

The next implemented layer is a separate root-signed node manifest.

That manifest lives beside node announcements.

It is posted to the registry through `POST /node-manifest`.

The manifest says, in effect:

- this root key currently owns this `node_id`
- these operational node keys are currently valid
- these roles and capabilities are currently valid
- these operational keys may be active or revoked

Current manifest fields:

- `node_id`
- `root_public_key`
- `manifest_version`
- `issued_at`
- `keys`
- `signature`

Each manifest key entry carries:

- `node_public_key`
- `role`
- `capabilities`
- `status`: `active` or `revoked`
- optional `expires_at`

If the same restaurant wants to move the `node_id` to a new root key, the registry also requires a previous-root rotation proof:

- `node_id`
- `previous_root_public_key`
- `next_root_public_key`
- `rotated_at`
- `signature`

That proof is signed by the previous root key.

In the current skeleton, the registry enforces:

- `manifest_version` must increase
- `manifest.issued_at` must move forward
- root-key change is accepted only with a valid previous-root signature
- revoked or expired manifest keys disappear from discovery immediately
- revoked or expired manifest keys can no longer send accepted heartbeats
- later announcements must still carry a matching delegation for the active manifest entry

## Node Identity Log Direction

The next identity layer should be a node-owned, registry-recorded log.

The registry may keep an append-only record of signed node identity events.

The current reference implementation keeps this log in memory and exposes it through `GET /identity-log`.

Only successfully verified signed announcements enter the log.

Unsigned legacy nodes remain accepted during early development, but they do not create identity-log records.

That log should store public identity facts:

- `node_id`
- `node_public_key`
- signed announcement metadata
- first seen
- last seen
- status such as active, revoked, or rotated

It must not store node private keys.

A later registry-signed log or snapshot can let clients verify that a registry is showing a consistent history.

The intended verification chain is:

1. node signs announcement
2. registry verifies node signature
3. registry records identity event
4. registry signs log or snapshot later
5. client verifies both node signature and registry log signature

This is a transparency layer, not a central approval layer.

## Backup Registries And Backup Nodes

A backup registry does not need node private keys.

It only needs the same signed announcement and heartbeat flow as the primary registry.

If the primary registry is unavailable, a client can still discover the node through a backup registry and verify the node signature.

A hosted backup node is different from a backup registry.

If a provider hosts a backup node for a restaurant, the long-term model should use delegated operational keys.

The restaurant's root node identity should be able to sign a delegation that says a hosted backup key may announce or operate for a limited purpose.

The hosted backup node should not require permanent access to the restaurant's root private key.

The current skeleton takes only the first small step in that direction:

- a node can announce itself with delegated role `primary` or `backup`
- the registry can verify that the root key authorized that operational node key
- a root manifest can now revoke that operational key or move the node id to a new root key
- actual backup-node data sync and failover behavior are still later layers

## Local And Development Nodes

Local and development nodes may sign announcements.

That is useful for testing the same trust flow locally.

Local and development identities should not automatically enter a public identity log.

Public identity logs should distinguish public production nodes from local, test, and demo nodes.

## Key Storage

The reference demo supports:

- `P4P_NODE_KEY_FILE`
- `P4P_NODE_PRIVATE_KEY`

If `P4P_NODE_KEY_FILE` is set and the file does not exist, the node creates an Ed25519 keypair and stores it there.

If neither is set, the demo node generates an ephemeral key at startup.

Ephemeral keys are acceptable for short local demos.

Real nodes should persist their private key.

## What This Does Not Prove

Node identity does not prove:

- the restaurant approved live orders
- the node is controlled by a specific company
- a CVR number matches the node
- a module provider is trustworthy
- a registry is trustworthy

Those are later signed claims.

The current lifecycle skeleton still does not solve:

- lost-root recovery
- restaurant-to-many-node manifest governance
- sync semantics between primary and backup nodes

The important improvement is narrower:

once a node id is signed, only the holder of that node private key can produce valid newer updates for it at a registry that has already accepted that identity.
