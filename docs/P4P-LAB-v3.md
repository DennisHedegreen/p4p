# P4P Lab v3

Local control-plane model for turning `lab/` from a hardcoded fixture bench into a real persistent test environment.

This is still not part of the protocol contract.

It is the local room for:

- infrastructure control
- registry topology control
- node-instance creation
- public customer-surface testing
- repeatable flow execution
- persistent local state between test sessions

## Why v3 exists

`P4P Lab v2` is already useful.

It can:

- start real local registries
- start real local pilot-node profiles
- show public customer surfaces
- run HTTP-first fixtures
- keep legacy proof lanes secondary

But it still reads too much like a hardcoded control page.

The current pressure points are real:

- too many fixed profiles
- too much truth locked in `lab/scenarios.json`
- no real server inventory page
- no clean split between templates and instances
- no way to create new test nodes in the UI and keep them between sessions
- no explicit page for seeing which port belongs to which layer

`v3` should solve that without moving this power into the protocol or the node operator.

## Summary

`P4P Lab v3` should become the canonical local control plane for the whole P4P test stack.

The core move is:

- `scenarios.json` stops being the master truth for everything
- it becomes seed/default data
- the real local working truth moves into a persistent lab state

Short rule:

**seed from config, operate from state**

## Current first-slice reality

The first `v3` slice now exists in code.

It already provides:

- persistent node-instance state in `lab/state/lab-state.sqlite3`
- a dedicated `/servers` page
- a dedicated `/topology` page
- a visible split between `Node Templates` and `Node Instances`
- UI-created node instances with generated service names, generated ports, and derived public/operator links
- instance-owned `registry_targets`, `visibility_expectations`, `module_ids`, and `menu_seed` for generated node instances
- instance-owned `node_id`, `city`, `country`, `categories`, and `order_mode` for generated node instances
- instance-owned `public_surface_key` so each generated node can choose its primary customer/public lane instead of inheriting only the template default
- local registry-lane overrides for `title`, `description`, `upstreams`, `announce_policy`, `discover_policy`, and `notes` through the `/topology` page
- generated registry-lane instances created from shipped registry templates, with their own local state, generated service names, generated registry ports, and start/stop control through the topology room
- generated local flow scenarios created on the main lab page, stored in local state, and runnable through the same HTTP-first fixture engine as the shipped seed flows
- a less hardcoded local flow-builder UI, where services, node targets, and fixture runs are assembled from live lab-state selectors instead of only being typed as freeform textarea syntax
- generated local customer fixtures created on the main lab page, stored in local state, targetable at either shipped node profiles or generated node instances, and runnable through the same HTTP-first fixture engine as the shipped seed fixtures
- a more human-friendly fixture/flow builder, where both create forms and local edit forms now read as step-based wizards with live preview summaries instead of only exposing the underlying model fields
- first-class editable flow checks for generated local flows, so saved flow scenarios can now keep explicit local success contracts in state instead of only relying on hidden auto-generated defaults
- a more human-friendly node/topology editor layer, where generated node instances and registry lanes now use step-based edit flows with preview summaries rather than only exposing raw state-patch fields
- a more human-friendly server inventory layer, where `/servers` now opens with a top summary of what is alive, which ports matter, and what to open first, and where each service card explains its port story and attached layers before the raw logs
- a more human-friendly grouped-ops layer on `/servers`, where registry lanes and node runtimes can now be started or stopped as local operation families instead of only as isolated raw per-process buttons
- a dedicated `/control` room, where those grouped runtime families are read as local control rooms with `What this room is for`, `Start path`, `Recovery path`, `Open this room first`, and attached live-layer links instead of only as service groups inside the raw server inventory
- a dedicated `/runs` room, where the recent fixture and flow history is read as human proof with `What the recent runs say`, `Latest proof`, per-run `Run story`, and `Run contract` summaries instead of only living as a smaller sidebar on the main lab page
- a proof-lane layer inside `/runs`, where the run history can be filtered by outcome, run kind, owner lane, public/customer layer, and registry path, then regrouped as `Proof lanes in this room` instead of only reading as a flat chronological stack
- a runs drill-down layer inside `/runs`, where each proof lane can now `Show matching runs`, push the owner-lane filter directly, and point the user toward the `First matching run` instead of leaving proof-lane navigation as passive summary text
- a more human-friendly recover/adopt layer on `/servers`, where individual runtimes now expose explicit `Restart`, `Recover`, and `Adopt` semantics instead of pretending every problem is the same as a raw start/stop click
- a dependency-aware server-room layer on `/servers`, where grouped node operations can now project and follow registry-first startup order instead of treating every service as independent
- a bind-truth layer on `/servers`, where each runtime now projects a `Truth owner` and generated node/lane runtimes can `Rebind` a live port under the right local owner instead of leaving adoption as anonymous port theater
- a grouped bind-truth layer on `/servers`, where room-level operations now project which owners live in the room and which ones `Recover` would rebind, so grouped restart/recovery stops reading as pure service order detached from node or lane meaning
- a flow owner-truth layer on the main lab page, where fixture runs, flow previews, saved local cards, and recorded run history now also project `Target owner`, `Local owners`, `Public/customer layers`, and `Registry path`, so flow execution can be read as local lane truth instead of only service ids plus synthetic customer traffic
- a run-story layer on the main lab page, where the runs API now projects a local summary of success mix, run kinds, owners touched, layers touched, and registry lanes touched, and `Recent Runs` now renders that as a human `What the recent runs say` summary plus a `Run story` on each recorded run
- a runtime-story layer in the node-instance and registry-lane editors, where create/edit previews now also project `Runtime lane`, `Open first`, and `What this changes`, and the saved node/lane cards now explain which service and port they become before the user falls back to raw status or config details
- a dedicated `/nodes` room, where seeded templates, persistent node instances, and projected customer/public surfaces now live as one local node workbench with `Seed templates in this room`, `Node instances in this room`, and `Customer/public surfaces in this room` instead of remaining only as scattered front-page sections
- a nodes-filter layer inside `/nodes`, where the room can now be narrowed by family, order mode, registry lane, owner kind, and public/customer surface, then re-read through a `Matching node lanes` summary before dropping into the filtered cards

The remaining honest limitation is:

- generated instances now own their registry targets, module set, and menu seed
- generated instances now also own their visible node identity fields and public-lane metadata
- generated instances can now choose which stored customer surface is the primary public lane
- registry lanes can now carry local lab-side topology overrides, but those overrides still change lab meaning-truth rather than registry process behavior
- extra generated registry lanes can now exist beside the shipped seed lanes, and generated node instances can now target those generated lanes directly
- extra generated local flow scenarios can now exist beside the shipped seed flows, and those local flows can target both shipped node profiles and generated node instances
- but seeded template-backed instances still stay mostly config-derived
- topology is now readable as a first-class page and has a first editable override layer, but it is still not a full registry-lane runtime editor

## The Boundary

### Hardcoded is allowed only for:

- the main open registry lane
- its backup
- default curated-lane seeds
- default port ranges
- default node templates
- fallback fixture templates

### Dynamic in the UI should cover:

- node instances
- extra registry instances
- public surfaces
- customer fixtures
- test flows
- link bundles
- local notes and tags

That means the lab can stay opinionated without staying rigid.

## The Main Model

`v3` should split the lab into three layers.

### 1. Seed layer

Repo-tracked JSON files that ship defaults:

- registry profile seeds
- node template seeds
- fixture seeds
- flow seeds

This is the versioned baseline.

### 2. Persistent local state

A local state store that survives restarts and keeps Dennis' actual working lab alive between sessions.

This should hold:

- created node instances
- custom registry instances
- chosen ports
- enabled/disabled flows
- saved fixtures
- recent runs
- notes
- tags
- topology overrides

Default choice:

- SQLite

Suggested file:

- `lab/state/lab-state.sqlite3`

Why SQLite:

- many small related objects
- safe local persistence
- simple filtering/querying later
- better than turning JSON into a mini database

### 3. Runtime process layer

The live process manager remains the single owner of local subprocesses.

It reads:

- seed definitions
- persistent state

and projects:

- current service truth
- current instance truth
- current link truth
- current run truth

## The New Page Model

`v3` should stop being one big control page with sections only.

It should become a small local app with real pages.

## 1. Servers

Purpose:

- see every running or known local process
- understand ports and layers quickly

Each row should show:

- service name
- process role
- port
- host
- PID
- cwd
- command
- health
- started at
- started by lab vs adopted external
- open links

Each server should also show its attached layers:

- registry
- operator
- public customer menu
- raw API
- status page

This is the page Dennis should open when he asks:

“what is running right now, on which port?”

## 2. Registry Topology

Purpose:

- understand open vs curated meaning lanes
- understand primary vs backup availability lanes

This page should show:

- `main-open`
- `main-open-backup`
- `dk-p4p-curated`
- `dk-p4p-curated-backup`

For each lane:

- scope
- curation mode
- availability role
- upstreams
- announce policy
- discover policy
- backing service
- current health
- visible nodes

This page is topology truth, not just service truth.

## 3. Node Templates

Purpose:

- define reusable node shapes without instantly starting them

Examples:

- `pizza-shop`
- `kebab-shop`
- `menu-only`
- `cash-only`
- `photo-map`

Each template should define:

- default modules
- default public surfaces
- default registry targets
- default order mode
- default tags
- default menu seed
- default notes

Templates are versioned defaults.

They are not running instances.

## 4. Node Instances

Purpose:

- create, edit, duplicate, and remove actual test nodes

This is the biggest `v3` shift.

Dennis should be able to create a new node in the UI by choosing:

- template
- node id
- public name
- ports
- registries
- enabled modules
- menu seed
- whether it should expose list-menu, photo-map, status page, operator

Instances should then persist locally and be startable/stoppable from the UI.

Short rule:

**templates are reusable shapes; instances are the actual test nodes**

## 5. Public Surfaces

Purpose:

- test the public customer side as a first-class surface

This page should make it easy to open:

- shop front page
- list menu
- photo-map menu
- status page
- raw menu JSON
- order endpoint
- status API

It should also show which node instance each surface belongs to.

This is where the whole public pizzeria or kebab surface becomes visible and testable, not just the operator.

## 6. Fixtures

Purpose:

- manage synthetic customer actors and request shapes

Fixtures should become editable local objects, not just hardcoded entries.

Examples:

- `pickup-basic`
- `kebab-rush`
- `status-poller`
- `bad-phone`
- `empty-cart`

Each fixture may target:

- one node template
- one node instance
- one public surface type

## 7. Flow Runner

Purpose:

- compose and execute many local flows without hardcoding them into code

A flow should be able to choose:

- required registries
- required node instances
- required fixtures
- checks
- expected visibility
- expected order outcome

Examples:

- `single-pizza-order`
- `single-kebab-order`
- `dual-shop-local`
- `announce-main-only`
- `approve-into-dk-curated`
- `main-down-curated-up`

## 8. Runs

Purpose:

- keep a readable trace of what was tested

The page should show:

- flow id
- fixture id
- target node
- created order id
- timestamps
- success/failure
- error detail
- links back to the used public surface and status route

`v3` should keep more than only ephemeral in-memory run data.

Default persistence:

- recent runs in SQLite

## State Model

`scenarios.json` should remain, but as seed data only.

Suggested split:

- `lab/scenarios.json`
  - shipped defaults
- `lab/state/lab-state.sqlite3`
  - persistent local objects
- `lab/state/exports/`
  - optional JSON exports/imports of user-created lab setups

## First v3 Rules

### Rule 1

The main open registry lane may remain more fixed and persistent than everything else.

Dennis explicitly wants this.

That means the lab may preserve:

- main registry identity
- main registry notes
- default discover assumptions

across many test sessions.

### Rule 2

Node creation must not require editing repo JSON by hand.

If a new pizza shop, kebab shop, or custom node requires hand-editing `scenarios.json`, `v3` is still incomplete.

### Rule 3

Customer/public testing is equal to operator testing.

The public menu and public shop surface are not secondary.

They need their own page and their own truth model.

### Rule 4

Topology meaning is separate from service uptime.

The server page answers:

- what is running?

The topology page answers:

- what does this registry lane mean?

## Migration Path

### Step 1

Keep `lab/scenarios.json` but treat it as seed/default input.

### Step 2

Add persistent local state for:

- node instances
- custom fixtures
- saved runs
- page preferences

### Step 3

Split the GUI into real pages:

- Servers
- Registry Topology
- Node Templates
- Node Instances
- Public Surfaces
- Fixtures
- Flow Runner
- Runs

### Step 4

Move the current hardcoded node profiles into template seeds and let instances be created from them.

## Non-Goals

`v3` should not:

- become a public hosted control plane
- require remote SSH orchestration
- become `node-control`
- redefine the P4P wire contract
- force the operator to absorb local multi-node lab power

## Practical Reading

`v2` is the working local bench.

`v3` is the next real shape for turning it into:

- less hardcoded
- more persistent
- more page-oriented
- more public-surface aware
- more useful as Dennis' daily local P4P test room
