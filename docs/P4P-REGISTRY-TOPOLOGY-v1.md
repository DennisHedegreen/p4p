# P4P Registry Topology v1

Local topology model for testing `open + curated` registry lanes inside `lab/`.

This is not a wire-contract change.

It is the first explicit model for how the local lab should think about:

- one broad uncurated registry lane
- one narrower curated sub-registry lane
- backup/failover for both
- node announcement policy
- discovery-path testing

## Summary

The current lab already knows how to start multiple registries:

- `primary-registry`
- `secondary-registry`
- `backup-registry`

That is enough for availability testing.

It is not enough for meaning.

The next real topology needs two separate axes:

1. **availability**
   - primary
   - backup
   - failover
2. **curation**
   - open
   - curated

The important correction is:

`secondary` must not automatically mean `sub-registry`.

A sub-registry is not just another copy on another port.

It is a different discover surface with a different scope and a different visibility rule.

## The Model

### 1. Open main registry

The open main registry is the broad intake lane.

It should be read as:

- uncurated
- protocol-first
- broad scope
- accepts valid node announcements
- does not try to be a brand directory

This is the closest thing to the raw network truth.

### 2. Curated sub-registry

The curated sub-registry is a narrower lane.

It should be read as:

- scoped
- filtered
- intentionally narrower than the main registry
- allowed to hide nodes that still exist in the open lane
- allowed to rank or present nodes differently

The first concrete example is:

- `DK Pizza4People`

That means:

- geography: Denmark
- family: shop
- brand/network: Pizza4People

It is a real discovery lane, not just a backup.

### 3. Backup registries

Backups are about continuity, not meaning.

Each meaning lane can have its own backup:

- open main backup
- curated sub backup

So the full first topology is:

- `main-open`
- `main-open-backup`
- `dk-p4p-curated`
- `dk-p4p-curated-backup`

## Why This Matters

Without this distinction, the lab can only answer:

- is the registry up?
- is failover working?

With this distinction, the lab can also answer:

- where is a node visible?
- what kind of registry made it visible?
- does visibility come from raw announcement or curation?
- does the curated lane survive independently of the open lane?

That is the real federation/curation test.

## v1 Registry Profiles

The first four profiles should be:

### `main-open`

- role: `main`
- curation mode: `open`
- availability role: `primary`
- scope:
  - network: `p4p`
  - geography: `global`
  - family: `any`

Purpose:

- broad discover lane
- broad announce lane
- no brand curation

### `main-open-backup`

- role: `main`
- curation mode: `open`
- availability role: `backup`
- backup for: `main-open`
- scope:
  - network: `p4p`
  - geography: `global`
  - family: `any`

Purpose:

- open-lane failover

### `dk-p4p-curated`

- role: `sub`
- curation mode: `curated`
- availability role: `primary`
- scope:
  - network: `pizza4people`
  - geography: `DK`
  - family: `shop`

Purpose:

- narrow discover lane for the Denmark Pizza4People universe
- can hide still-valid nodes that remain visible in `main-open`

### `dk-p4p-curated-backup`

- role: `sub`
- curation mode: `curated`
- availability role: `backup`
- backup for: `dk-p4p-curated`
- scope:
  - network: `pizza4people`
  - geography: `DK`
  - family: `shop`

Purpose:

- curated-lane failover

## `lab/scenarios.json` Additions

The current v2 lab shape should grow one new top-level section:

- `registry_profiles`

So the widened config becomes:

- `version`
- `services`
- `registry_profiles`
- `node_profiles`
- `customer_fixtures`
- `flow_scenarios`
- `legacy_scenarios`

### `registry_profiles`

This section is metadata over launchable registry services.

Suggested fields:

- `id`
- `title`
- `description`
- `service_name`
- `role`
  - `main`
  - `sub`
- `curation_mode`
  - `open`
  - `curated`
- `availability_role`
  - `primary`
  - `backup`
- `backup_for`
  - nullable registry profile id
- `scope`
  - object with:
    - `network`
    - `geography`
    - `family`
- `upstreams`
  - list of registry profile ids this profile may read from or mirror
- `announce_policy`
  - `direct`
  - `mirrored`
  - `allowlist`
- `discover_policy`
  - `raw`
  - `filtered`
  - `ranked`
- `notes`

### Example shape

```json
{
  "registry_profiles": {
    "main-open": {
      "id": "main-open",
      "title": "Main Open Registry",
      "description": "Broad uncurated P4P registry lane.",
      "service_name": "primary-registry",
      "role": "main",
      "curation_mode": "open",
      "availability_role": "primary",
      "backup_for": null,
      "scope": {
        "network": "p4p",
        "geography": "global",
        "family": "any"
      },
      "upstreams": [],
      "announce_policy": "direct",
      "discover_policy": "raw",
      "notes": [
        "Accepts broad valid announcements.",
        "Does not behave like a brand directory."
      ]
    },
    "main-open-backup": {
      "id": "main-open-backup",
      "title": "Main Open Backup",
      "description": "Failover lane for the broad open registry.",
      "service_name": "backup-registry",
      "role": "main",
      "curation_mode": "open",
      "availability_role": "backup",
      "backup_for": "main-open",
      "scope": {
        "network": "p4p",
        "geography": "global",
        "family": "any"
      },
      "upstreams": [],
      "announce_policy": "direct",
      "discover_policy": "raw",
      "notes": [
        "Backup for the open lane."
      ]
    },
    "dk-p4p-curated": {
      "id": "dk-p4p-curated",
      "title": "DK Pizza4People Registry",
      "description": "Curated Denmark Pizza4People lane.",
      "service_name": "secondary-registry",
      "role": "sub",
      "curation_mode": "curated",
      "availability_role": "primary",
      "backup_for": null,
      "scope": {
        "network": "pizza4people",
        "geography": "DK",
        "family": "shop"
      },
      "upstreams": [
        "main-open"
      ],
      "announce_policy": "allowlist",
      "discover_policy": "filtered",
      "notes": [
        "Can expose a narrower set than the open lane.",
        "Curation and discoverability are not the same thing as raw announcement."
      ]
    },
    "dk-p4p-curated-backup": {
      "id": "dk-p4p-curated-backup",
      "title": "DK Pizza4People Backup",
      "description": "Backup curated Denmark Pizza4People lane.",
      "service_name": "curated-backup-registry",
      "role": "sub",
      "curation_mode": "curated",
      "availability_role": "backup",
      "backup_for": "dk-p4p-curated",
      "scope": {
        "network": "pizza4people",
        "geography": "DK",
        "family": "shop"
      },
      "upstreams": [
        "dk-p4p-curated",
        "main-open"
      ],
      "announce_policy": "allowlist",
      "discover_policy": "filtered",
      "notes": [
        "Backup for the curated DK lane."
      ]
    }
  }
}
```

## Node-Profile Additions

Node profiles should also gain explicit registry-lane intent.

Suggested fields:

- `registry_targets`
  - list of registry profile ids the node should announce to
- `visibility_expectations`
  - list of registry profile ids where the node is expected to appear

Example:

```json
{
  "id": "pizza-shop",
  "service_name": "pilot-pizza-shop",
  "registry_targets": [
    "main-open"
  ],
  "visibility_expectations": [
    "main-open"
  ]
}
```

Later, after curation:

```json
{
  "id": "pizza-shop",
  "service_name": "pilot-pizza-shop",
  "registry_targets": [
    "main-open"
  ],
  "visibility_expectations": [
    "main-open",
    "dk-p4p-curated"
  ]
}
```

This is the core distinction:

- announcement target
- visible discover lane

are not automatically identical.

## Flow Scenarios To Add

The first topology-aware flows should be:

### `announce-main-only`

Success means:

- node appears in `main-open`
- node does not appear in `dk-p4p-curated`

### `approve-into-dk-curated`

Success means:

- node remains in `main-open`
- node now also appears in `dk-p4p-curated`

### `main-down-curated-up`

Success means:

- open main lane can fail
- curated DK lane still answers

### `curated-down-main-up`

Success means:

- raw open discover still works
- curated lane is unavailable

## UI Implication For Lab

The lab should stop showing registries only as flat processes.

It should show:

- profile title
- open vs curated
- primary vs backup
- scope
- upstream relationship

So the operator of the lab can read:

- what is running
- what kind of registry it is
- what lane of discoverability it represents

## Non-goals

This spec does not yet define:

- how curated promotion records are stored
- how manual approval happens
- how trust claims and moderated directory interact with the sub-registry
- cross-machine deployment

It is only the first local topology model for the lab.

## Short Rule

Primary/backup answers:

- **can the lane survive?**

Open/curated answers:

- **what kind of lane is it?**

Both axes are necessary.
