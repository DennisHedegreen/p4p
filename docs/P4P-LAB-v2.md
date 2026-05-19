# P4P Lab v2

Local orchestration panel for real P4P infrastructure plus synthetic test fixtures.

This is not part of the protocol contract.

It is the local control surface above registries, pilot nodes, customer fixtures, and flow tests.

## Summary

`P4P Lab` should become the canonical local admin and test-flow panel for:

- starting and stopping registries
- starting and stopping pilot nodes
- choosing real node profiles
- choosing synthetic customer profiles
- running local order-flow scenarios
- observing health, logs, and failover

The important boundary is:

- **real infrastructure is allowed**
- **synthetic fixtures are allowed**
- **fake product theater is not**

That means:

- a local `pizza-shop` node profile is fine
- a local `kebab-shop` node profile is fine
- a local `rush customer` profile is fine
- but the lab should no longer pretend that fake pizzeria stories are the product itself

## Why it exists

The protocol and the pilot node should stay clean.

The operator is for controlling one running node.

The lab is for orchestrating multiple local processes and testing flows across them.

`lab/` is therefore the right place for:

- local topology
- process control
- fixture profiles
- failure simulation
- repeatable test scenarios

It is not the right place to redefine the protocol.

## v2 Direction

The current lab already starts local services from `lab/scenarios.json`.

The v2 direction is to make that panel read less like a legacy proof bench and more like a real local control surface.

### The panel should directly control:

- primary registry
- secondary or sub registry
- backup registry
- one or more pilot nodes
- optional static or customer test surfaces
- optional inspection helpers

### The panel should directly show:

- running vs stopped
- ready vs not ready
- health endpoint result
- registration state
- command used to start the service
- logs
- important open links

## The new boundary

### Allowed in Lab

- synthetic shop profiles
- synthetic customer profiles
- synthetic order fixtures
- local failover tests
- local network or process topology tests

### Not allowed as the main story

- fake demo nodes as the primary product narrative
- hardcoded pizzeria theater as the default public proof
- hidden legacy batch spawners as the main workflow

Short rule:

**fixtures stay in the lab, not in the product story**

## v2 Surface Model

The panel should be organized into five layers.

### 1. Infrastructure

This section controls real local processes:

- start primary registry
- start secondary registry
- start backup registry
- stop any registry
- view registry health
- open registry inspection routes

This is the local infrastructure truth layer.

### 2. Node Profiles

This section starts real pilot-node processes using named profiles.

Examples:

- `pizza-shop`
- `kebab-shop`
- `menu-only`
- `cash-only`
- `pickup-board`
- `kitchen-heavy`

These are not public marketing categories.

They are local runtime fixtures for repeatable tests.

Each profile should define:

- base URL / port
- registry URLs
- node id
- node name
- order mode
- module set
- menu fixture source
- operator token source
- optional hardware or pickup-board flags

### 3. Customer Fixtures

This section defines synthetic customer personas for local tests.

Examples:

- `walk-in-customer`
- `pickup-customer`
- `rush-customer`
- `late-customer`
- `error-customer`

Customer fixtures should be allowed to drive:

- menu choice
- item selection
- quantity
- name / pickup note
- order submission timing
- bad-input tests
- status-page polling behavior

These are test actors, not user accounts.

### 4. Flow Scenarios

This section runs repeatable flows that combine infrastructure, node profiles, and customer fixtures.

Examples:

- `single-node local order`
- `pizza + kebab dual-node test`
- `menu-only dry run`
- `fail primary registry, keep backup alive`
- `operator module change then restart`
- `customer status follow-up`

Each scenario should declare:

- which services to start
- which node profiles to launch
- which customer fixture to use
- which URLs to open
- what success looks like

### 5. Observability

This section shows local truth across the running stack:

- health
- logs
- registry registration state
- operator routes
- customer routes
- ready vs unreachable
- scenario notes

The panel should be a real ops bench, not a button wall.

## Current v2 Reality

The first implementation now exists in code.

It already provides:

- `Infrastructure`
  - backed by real local registry services
  - now shown through explicit `registry_profiles`
- `Node Profiles`
  - real pilot-node launch profiles such as `pizza-shop`, `kebab-shop`, and `menu-only`
- `Customer Surfaces`
  - first-class public shop links for the running node profiles
  - raw `menu`, `order`, and `status` routes beside them
- `Customer Fixtures`
  - HTTP-first synthetic actors using the real public endpoints
- `Flow Scenarios`
  - repeatable local multi-step runs
- `Legacy Proof`
  - still present, but secondary
- `Services & Logs`
  - raw process truth

The remaining honest limitation is this:

- the lab now models `open` versus `curated` registry topology explicitly
- but the registry runtime is still the same protocol process underneath
- so branded curation meaning is modeled honestly in the lab layer before it is enforced as a deeper runtime policy

## Config Model

The current config-driven direction stays right.

`lab/scenarios.json` should remain the center of the GUI.

But v2 should separate data more clearly:

- `services`
- `registry_profiles`
- `node_profiles`
- `customer_fixtures`
- `flow_scenarios`

That separation matters because:

- services describe processes
- registry profiles describe open vs curated meaning lanes above those processes
- node profiles describe runtime identity and module shape
- customer fixtures describe test actors
- scenarios describe composed flows

The next topology layer above this split is written in:

- `docs/P4P-REGISTRY-TOPOLOGY-v1.md`

## Legacy vs v2

Some current lab behavior is still legacy:

- `demo-node-*`
- batch node spawning
- hardcoded `P4P Test Pizzeria`
- `pizza,kebab` defaults baked into the old helper path

These are acceptable as temporary compatibility paths.

They should not stay the main lane.

The main v2 lane should be:

- start registry stack
- start named pilot-node profile
- open operator
- open customer surface
- run customer fixture
- watch logs and health

## Non-goals

Lab v2 is not:

- part of the protocol contract
- a public production control plane
- a hidden registry admin backdoor
- the restaurant operator itself
- a replacement for `node-control`

The operator remains the local owner-facing room for one node.

The lab remains the local orchestration bench.

## First concrete migration

The first real v2 pass should do this:

1. Keep the existing config-driven panel.
2. Stop treating legacy demo-node spawning as the main workflow.
3. Add explicit named pilot-node profiles to config.
4. Add synthetic customer fixtures as first-class config entries.
5. Add explicit flow scenarios built from those pieces.
6. Rename the GUI language toward `Infrastructure`, `Node profiles`, `Customer fixtures`, and `Flows`.

That gives a real local test-flow panel without polluting the protocol or pretending the fixtures are the product.

## Short rule

Build the lab as:

**real local processes + synthetic local fixtures + honest boundaries**
