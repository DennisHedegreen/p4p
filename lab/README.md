# P4P Lab

Separate local harness for testing the P4P protocol without polluting the protocol room itself.

This is not part of the protocol.

It is a browser control panel for:
- starting and stopping configured local scenarios
- starting and stopping local registries
- starting and stopping demo or pilot nodes
- watching service logs
- opening links for the running services
- reading the exact command each service was started with
- stress-testing discovery with multiple nodes

## Why it exists

The repo root should stay protocol-first.

`lab/` is the operational bench for local debugging and multi-node testing.

It is explicitly not part of the protocol contract.

The next product direction for this room is written in:

- `docs/P4P-LAB-v2.md`
- `docs/P4P-LAB-v3.md`
- `docs/P4P-REGISTRY-TOPOLOGY-v1.md`

Short version:

- real local registries and pilot nodes stay here
- synthetic shop and customer fixtures stay here
- fake product-story theater should not stay the main lane

## Run

```bash
cd /path/to/p4p/lab
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/uvicorn app:app --reload --port 8899
```

Open:

`http://127.0.0.1:8899`

Dedicated server inventory page:

`http://127.0.0.1:8899/servers`

Dedicated control-rooms page:

`http://127.0.0.1:8899/control`

Dedicated runs room:

`http://127.0.0.1:8899/runs`

Dedicated registry-topology page:

`http://127.0.0.1:8899/topology`

## Scenario Config

The main GUI is driven by `lab/scenarios.json`.

That file declares:

- `services`
- `registry_profiles` (next topology layer)
- `node_profiles`
- `customer_fixtures`
- `flow_scenarios`
- `legacy_scenarios`

The GUI should not need code changes when adding a local test command. Add a
service, profile, fixture, or scenario to `lab/scenarios.json`, restart or refresh the lab, and the
new button/link/command appears in the browser.

The current `v3` slice now also seeds persistent node-instance state into:

- `lab/state/lab-state.sqlite3`

That state file is local working truth for node instances. `lab/scenarios.json`
remains the seed/default layer, while user-created instances now get their own generated
service names, ports, derived public/operator links, and instance-owned:

- `registry_targets`
- `visibility_expectations`
- `module_ids`
- `menu_seed`
- `node_id`
- `city`
- `country`
- `categories`
- `order_mode`
- `public_surface_key`

Current configured main lanes:

- local registries:
  - `primary-registry`
  - `secondary-registry`
  - `backup-registry`
  - `curated-backup-registry`
- registry topology profiles:
  - `main-open`
  - `main-open-backup`
  - `dk-p4p-curated`
  - `dk-p4p-curated-backup`
- pilot-node profiles:
  - `pizza-shop`
  - `kebab-shop`
  - `menu-only`
- customer/public surfaces:
  - real list-menu public shop for `pizza-shop`
  - real list-menu public shop for `kebab-shop`
  - real dry-run public shop for `menu-only`
  - raw menu/order/status endpoints beside each public shop
- customer fixtures:
  - `pickup-basic`
  - `kebab-rush`
  - `status-poller`
- flow scenarios:
  - `single-pizza-order`
  - `single-kebab-order`
  - `dual-shop-local`
  - `fail-primary-keep-backup`

Current legacy lanes:

- `pilot-photo-map-menu`
- `registry-client-demo-node`

Those legacy scenarios now stay as compatibility and proof history, not as the
main workflow for the lab.

## Notes

- `TEST-GUIDE.md` is the canonical rescue and proof sequence; `lab/README.md` is only the local harness quickstart.
- The panel expects the existing `registry/.venv` and `demo-node/.venv` runtimes to exist in the repo root.
- The configured pilot-node profiles expect `pilot-node/.venv` to exist.
- The new `registry_profiles` layer is topology metadata for the lab UI. It models open vs curated meaning lanes honestly, but it does not claim that the registry runtime itself now enforces branded curation policy.
- `docs/P4P-LAB-v3.md` is the next architectural step if this room should stop being mostly config-driven and become a persistent local control plane with created node instances, a server inventory page, explicit public-surface pages, and saved local lab state between sessions.
- The live first slice of that direction now exists: the main page distinguishes `Node Templates` from `Node Instances`, `/servers` gives the dedicated port-by-port inventory view, and generated node instances can now be launched through their own instance routes instead of staying draft-only.
- The next live slice also exists now: `/topology` makes the registry lanes readable as topology truth rather than only service truth, including open vs curated meaning lanes, primary vs backup availability lanes, upstreams, and the node templates and node instances attached to each registry profile.
- The next live ownership slice also exists now: generated node instances can keep their own registry targets, visibility expectations, module set, and menu seed in local state, and those values now flow all the way into the generated pilot-node service definition that the lab starts.
- The next live identity slice also exists now: generated node instances can also keep their own `node_id`, `city`, `country`, `categories`, and `order_mode` in local state, and those values now show up in the lab UI and flow into the generated pilot-node runtime instead of staying hidden inside the template service env.
- The next live public-lane slice also exists now: generated node instances can choose their own `public_surface_key`, so the primary customer-facing lane no longer has to stay fixed to the template fallback order. The lab UI now shows which public surface each instance actually uses, and `/topology` now explains `announces here` versus `visible here` more explicitly instead of only showing badges.
- The next live topology-ownership slice also exists now: `/topology` is no longer only read-only projection. Registry lanes can now keep local lab-side overrides for `title`, `description`, `upstreams`, `announce_policy`, `discover_policy`, and `notes`. That does not rewrite the registry runtime itself, but it does make the topology room a real local working truth instead of a pure config mirror.
- The next live registry-lane slice also exists now: `/topology` can create extra local registry lanes from the shipped registry templates, store them in `lab/state/lab-state.sqlite3`, give them generated service names and registry ports, and start/stop them as real local registry processes. Generated node instances can now also target those generated lanes directly through their own `registry_targets` and `visibility_expectations`.
- The next live flow-creator slice also exists now: the main lab page can create and save extra local flow scenarios in `lab/state/lab-state.sqlite3`, not only run the shipped seed flows from `lab/scenarios.json`. Those local flows can target both shipped node profiles and generated node instances, carry their own service list and fixture runs, and run through the same HTTP-first fixture engine as the seed scenarios.
- The next live flow-builder slice also exists now: the local flow editor is no longer only textarea-driven. The main page and generated-flow editor now build services, node targets, and fixture runs from live lab state with row-based selectors, so creating a new local flow no longer requires remembering service ids, node refs, and fixture syntax by hand.
- The next live local-fixture slice also exists now: `Customer Fixtures` is no longer locked to the shipped seed fixtures in `lab/scenarios.json`. The main lab page can now create and edit extra local customer fixtures in `lab/state/lab-state.sqlite3`, target either shipped node profiles or generated node instances, and feed those local fixtures directly into the same run button and flow builder as the seeded fixtures.
- The next live human-friendly builder slice also exists now: the create and edit forms for `Customer Fixtures` and `Flow Scenarios` are no longer only model-shaped row editors. They now read as small step-based wizards with helper copy and live preview summaries, so you can see what a local fixture or flow is about to do without mentally decoding raw ids first.
- The next live flow-check slice also exists now: generated local flows no longer have to live only on hidden auto-generated checks. The main create/edit lane can now own explicit `checks` as local state, refresh suggested checks from the current plan, or keep manual checks as the real test contract for a saved local flow.
- The next live node/topology UX slice also exists now: the generated node-instance editor on the main lab page and the registry-lane create/edit forms on `/topology` now read as step-based local control rooms with preview summaries, so node identity, public surface choice, registry targets, upstreams, and topology meaning can be shaped in human terms instead of only as raw patch fields.
- The next live server-ops slice also exists now: `/servers` no longer reads only as raw process rows. It now starts with a human summary of what is alive, which ports matter, and what to open first, and each service card explains its port story, attached layers, and best first link before you drop into raw health JSON or logs.
- The next live grouped-ops slice also exists now: `/servers` is no longer only a list of per-process buttons. It now exposes grouped human actions such as `Registry stack`, `Node runtimes`, and `Open the live layers`, so you can bring the registry lane family or the node runtime family up and down as local driftsrum operations instead of mentally repeating the same start/stop click on each row.
- The next live recover/adopt slice also exists now: `/servers` now exposes explicit `Restart`, `Recover`, and `Adopt` actions per runtime. That means the room can distinguish between a clean lab-owned restart, recovery from a stale cached runtime, and re-adoption of a service that is already alive on its expected port outside the current lab process.
- The next live dependency-aware drift slice also exists now: `/servers` now projects which services depend on which registry lanes, and grouped server actions use that plan instead of flat button order. The room can now show `Dependencies first`, `Bring up in this order`, and `Stop in this order`, so node runtimes can come up behind their required registries instead of pretending all services are independent.
- The next humane bind-truth slice also exists now: `/servers` now projects a `Truth owner` for each runtime, so adoption reads as “which node or registry lane owns this live port?” instead of just “something answered on this port”. Generated node and registry-lane runtimes can now use `Rebind` to forget stale port ownership and re-adopt the live service under the right local owner.
- The next grouped bind-truth slice also exists now: grouped rooms on `/servers` no longer speak only in service names and dependency order. They now also project `Truth owners in this room` plus `Recover rebinds these owners`, so registry-first recovery can still be read as local owner-truth instead of raw process theater.
- The next control-room slice also exists now: `/control` turns those grouped server families into a dedicated local room with `What this room is for`, `Start path`, `Recovery path`, `Open this room first`, and attached live-layer links, so grouped registry/runtime operations can be read as local control stories instead of only as raw service groups.
- The next runs-room slice also exists now: `/runs` turns the memory-only fixture and flow history into a dedicated human reading room, with `What the recent runs say`, `Latest proof`, per-run `Run story`, and `Run contract` summaries instead of forcing that reading to stay as a smaller side panel on the main lab page.
- The next proof-lane slice also exists now: `/runs` no longer reads only as one long history list. It now projects filter facets plus `Proof lanes in this room`, so the local run history can be narrowed by outcome, run kind, owner lane, public/customer layer, or registry path and then re-read as grouped owner-lane proof instead of only as raw chronological cards.
- The next runs drill-down slice also exists now: those proof lanes are no longer static summaries. Each lane can now `Show matching runs`, push the owner-lane filter directly, and jump the reader down to the relevant run cards, while the filter summary now also states the `First matching run` instead of making the user infer the next reading target alone.
- The next flow owner-truth slice also exists now: the flow runner and fixture runner no longer read only as services plus synthetic customer ids. Saved fixture/flow cards, live previews, and recorded runs now also project `Target owner`, `Local owners`, `Public/customer layers`, and `Registry path`, so the lab can say which local lane meaning was actually tested instead of only which buttons were pressed.
- The next run-story slice also exists now: `Recent Runs` no longer reads only as a stack of raw result cards plus JSON. The runs API now returns a local summary of success/failure mix, run kinds, owners touched, layers touched, and registry lanes touched, and the main lab page now renders that as a human `What the recent runs say` panel plus a `Run story` summary on each recorded run.
- The next runtime-story slice also exists now: the node-instance and registry-lane editors no longer stop at identity and topology fields. The create/edit previews now also project `Runtime lane`, `Open first`, and `What this changes`, and the saved node/lane cards now tell you which service and port they become before you drop into raw status or config details.
- The next nodes-room slice also exists now: `/nodes` turns the seeded templates, persistent node instances, and projected customer/public surfaces into one dedicated local workbench. Instead of only reading those lanes as scattered cards on the front page, the lab now has a room that says which runtime seed a node comes from, which local owner a surface belongs to, what to open first, and which registry path the lane is supposed to travel through.
- The next nodes-filter slice also exists now: `/nodes` no longer has to be read as one long mixed wall. The room can now be narrowed by family, order mode, registry lane, owner kind, and public/customer surface, and it explains the filtered result as `Matching node lanes` before you drop into the actual template, instance, and surface cards.
- It starts subprocesses locally and captures their stdout logs.
- It can spawn many demo nodes with distinct ports and slightly shifted coordinates.
- Spawned demo nodes dual-register to both primary and backup registries by default.
- The panel distinguishes between a running node process and a ready node by probing `/health`.
- In lab terms, `running` means the subprocess still exists. `ready` means the node's `/health` endpoint returns `200` with current registry registration state.
- The lab serves the reference client directly at `http://127.0.0.1:8765/`, not under `/client/`.
