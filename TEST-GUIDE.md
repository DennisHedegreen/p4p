# P4P v0.1 — Test Guide

This guide is for testing the current `v0.1` truth model.

The goal is not feature breadth.

The goal is to confirm that the system is honest:

- nodes dual-register to more than one registry
- client failover is real for discovery
- a node is only green when it is actually registered
- a closed node rejects orders
- direct `client -> node` flow stays intact after registry failover

## 1. What to test

There are two useful test layers:

1. automated truthfulness tests
2. live manual testing through `lab/`

Use both.

The automated tests catch contract regressions quickly.

The live lab pass proves the real user-visible flow.

## 2. Prerequisites

You need these runtimes available for the full rescue, proof, and pilot pass:

- `registry/.venv`
- `demo-node/.venv`
- `lab/.venv`
- `pilot-node/.venv`

For proof-only work, `registry/.venv`, `demo-node/.venv`, and `lab/.venv` are enough.

`pilot-node/.venv` is required for the local pilot gate in section 10.

If they do not exist yet, provision all four environments from the shared local
dependency lock:

```bash
cd /path/to/p4p
bash scripts/bootstrap-local.sh
```

The script creates the component-specific virtual environments expected by the
lab while constraining shared dependencies through `requirements.lock.txt`.

The equivalent manual setup is:

```bash
cd /path/to/p4p/registry
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

```bash
cd /path/to/p4p/demo-node
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

```bash
cd /path/to/p4p/lab
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

```bash
cd /path/to/p4p/pilot-node
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Ports to keep free if you use default settings:

- `8000` primary registry
- `8002` backup registry
- `8101` to `8125` demo nodes
- `8765` static client server
- `8899` lab panel

If `8899` is busy, start the lab on another port such as `8898`.

## 3. Rescue gate

Run this from `P4P/`:

```bash
cd /path/to/p4p
bash scripts/check-local.sh
```

The lifecycle tests use real AnyIO worker threads. Run the rescue gate in a
normal local shell or CI runner, not inside a sandbox that blocks thread wakeups.

What should pass:

- truthfulness and cleanup tests stay green
- public audit does not find tracked sensitive-looking files or hard secret literals
- client JavaScript parses cleanly
- shared runtime modules compile cleanly
- single-registry fallback still works
- dual registration makes the node discoverable in both registries
- closed nodes are excluded from discover and reject orders
- unreachable registries keep `/health` at `503`
- lab status can show `running` but not `ready`

If this suite is red, fix that first.

Do not trust a manual green flow until this suite is green again.

For a running narrow proof stack, run the read-only HTTP health matrix:

```bash
python3 scripts/health-check.py --mode local
```

Before public DNS is changed, run the same matrix against the candidate public
URLs in hosted mode:

```bash
python3 scripts/health-check.py \
  --mode hosted \
  --client https://client.pizza4people.com \
  --registry-a https://registry-a.pizza4people.com \
  --registry-b https://registry-b.pizza4people.com \
  --node https://demo-node.pizza4people.com
```

Hosted mode additionally refuses registries without SQLite persistence, stable
signing, a configured-but-closed admin boundary, baseline security headers, or a
common discoverable node.

The reference runtimes also enforce bounded request bodies. Public order routes
have an in-process per-client rate limit, while registry announce, heartbeat,
manifest, import, and sync writes use route-specific limits. These controls are
defense in depth; a hosted deployment must still enforce limits at its reverse
proxy because in-memory counters are not shared between workers or hosts.

Before accepting a hosted candidate, provision and audit its persistent signing
identities, tokens, and SQLite state with `scripts/runtime-state.py`. Create a
live-safe backup, verify its manifest, restore it into a new empty directory, and
audit the restored copy. Exact commands and ownership boundaries are in
`deploy/README.md`. A passing local recovery rehearsal is required evidence, but
it is not a substitute for repeating the drill on the actual hosts.

For the Docker/Railway-shaped runtime candidate, run:

```bash
bash scripts/check-container.sh
```

This is a local build and restart test. It does not create a Railway project,
attach a real volume, reserve a domain, or prove the independent backup host.

## 4. Start the live lab

Start the panel:

```bash
cd /path/to/p4p/lab
./.venv/bin/uvicorn app:app --reload --port 8899
```

Then open:

`http://127.0.0.1:8899`

Use the buttons in this order:

1. `Start Primary Registry`
2. `Start Backup Registry`
3. `Start Client Server`
4. `Spawn Batch`

Default batch size `10` is fine.

What you should see in the lab:

- both registries show as `running`
- the client link should open at `http://127.0.0.1:8765/`
- each node shows as `running`
- each node should turn `ready`
- each node health block should show:
  - `status: "ready"`
  - two configured registries
  - two registered registries

If a node is `running` but not `ready`, that is not a false alarm.

It means the process exists but registration is not current.

If `registered_registries` only shows primary and backup is still under `failed_registries`, either:

- backup registry is not actually up yet
- or the node has not hit its next heartbeat cycle yet

Default heartbeat interval is 60 seconds.

So either wait about a minute after starting backup, or stop and restart the node to force a fresh announce cycle immediately.

## 5. Single-registry smoke test

This is the smallest end-to-end check.

Steps:

1. start only `Primary Registry`
2. start `Client Server`
3. spawn one node
4. open the client from the lab link
5. click `Discover Nodes`
6. choose the node
7. fetch menu
8. place order

Expected result:

- node `/health` is `200`
- primary `/discover` returns the node
- menu loads directly from the node endpoint
- order succeeds
- demo-node log prints the order payload

## 6. True failover test

This is the important one.

Steps:

1. start primary registry
2. start backup registry
3. start client server
4. spawn one node or a full batch
5. open both discover links from the lab
6. confirm the same node or batch appears in both registries
7. open the client
8. run `Discover Nodes` once while both registries are up
9. stop the primary registry from the lab
10. run `Discover Nodes` again in the client

Expected result:

- the second discover still succeeds
- client status should show that failover happened
- backup registry now serves the discover result
- menu fetch still goes directly to node
- order still goes directly to node

What this proves:

- client failover is real for discovery
- node dual-registration is real
- registry shutdown does not break direct node traffic once node is selected

What this does not prove:

- registry sync
- order replication
- mid-order recovery

Those are not part of `v0.1`.

## 7. Closed-node behavior test

Run a node manually with `open=false`:

```bash
cd /path/to/p4p/demo-node
P4P_REGISTRY_URLS=http://127.0.0.1:8000,http://127.0.0.1:8002 \
P4P_NODE_BASE_URL=http://127.0.0.1:8201 \
P4P_NODE_OPEN=false \
./.venv/bin/uvicorn demo_node:app --port 8201
```

Expected result:

- the node process runs
- `/health` can still be `200` if registration is current
- the node is not returned by `discover`
- direct `POST /p4p/order` returns:
  - `accepted: false`
  - `reason: "closed"`

Important:

`ready` does not mean `open`.

It means the node is alive and properly registered.

## 8. False-green prevention test

Run a node against registries that do not exist:

```bash
cd /path/to/p4p/demo-node
P4P_REGISTRY_URLS=http://127.0.0.1:8990,http://127.0.0.1:8991 \
P4P_NODE_BASE_URL=http://127.0.0.1:8301 \
./.venv/bin/uvicorn demo_node:app --port 8301
```

Then inspect:

`http://127.0.0.1:8301/health`

Expected result:

- process is alive
- `/health` returns `503`
- `status` is `not_ready`
- `registered_registries` is empty
- `failed_registries` explains what failed

This is the test that protects against fake green.

## 9. Multi-node lab test

This is the real scale check for the current bench.

Steps:

1. start primary
2. start backup
3. start client server
4. spawn `10` nodes
5. verify primary discover returns the batch
6. verify backup discover returns the batch
7. stop primary
8. verify backup still returns the batch
9. stop one node
10. confirm the lab updates that node separately
11. restart that node
12. confirm it comes back as `ready`

What to watch:

- logs reflect process start and stop truthfully
- node health moves between `ready` and `not_ready`
- batch remains discoverable from backup after primary dies

## 10. Pilot-node local gate

This is the local dry run for the controlled live-pilot shape.

Start primary and backup registries first, then run the pilot node:

```bash
cd /path/to/p4p/pilot-node
P4P_PILOT_NODE_DB_PATH=/tmp/p4p-pilot-node.sqlite3 \
P4P_OPERATOR_TOKEN=change-this \
P4P_NODE_ORDER_MODE=menu_only \
P4P_REGISTRY_URLS=http://127.0.0.1:8000,http://127.0.0.1:8002 \
P4P_NODE_BASE_URL=http://127.0.0.1:8201 \
./.venv/bin/uvicorn pilot_node:app --port 8201
```

Then verify this sequence:

1. `GET /health` shows the node as running and registered.
2. `GET /operator/state` without a token returns `401`.
3. `PATCH /operator/state` with the bearer token can move the node from `menu_only` to `live`.
4. A direct `POST /p4p/order` succeeds only after the node is in `live` or `test`.
5. `GET /operator/orders` shows the stored order.
6. `PATCH /operator/orders/{order_id}` can move the order through `accepted`, `ready`, and `completed`.
7. `GET /operator/orders/{order_id}/events` stays available for module evidence or print-lane inspection.
8. After a restart, the stored order is still present in SQLite.
9. The operator can quickly return the node to `menu_only` or set `open=false`.

Useful local commands:

```bash
curl -sS http://127.0.0.1:8201/health

curl -sS http://127.0.0.1:8201/operator/state \
  -H 'Authorization: Bearer change-this'

curl -sS -X PATCH http://127.0.0.1:8201/operator/state \
  -H 'Authorization: Bearer change-this' \
  -H 'Content-Type: application/json' \
  -d '{"order_mode":"live"}'

curl -sS -X POST http://127.0.0.1:8201/p4p/order \
  -H 'Content-Type: application/json' \
  -d '{"customer_name":"Anna Hansen","customer_contact":"+4512345678","fulfillment":"pickup","items":[{"id":"kebab-pita","quantity":1}],"note":"Pilot dry run","client_version":"p4p-web-0.1"}'

curl -sS http://127.0.0.1:8201/operator/orders \
  -H 'Authorization: Bearer change-this'

curl -sS -X PATCH http://127.0.0.1:8201/operator/orders/<order_id> \
  -H 'Authorization: Bearer change-this' \
  -H 'Content-Type: application/json' \
  -d '{"status":"accepted","estimated_ready_minutes":15}'

curl -sS -X PATCH http://127.0.0.1:8201/operator/orders/<order_id> \
  -H 'Authorization: Bearer change-this' \
  -H 'Content-Type: application/json' \
  -d '{"status":"ready"}'

curl -sS -X PATCH http://127.0.0.1:8201/operator/orders/<order_id> \
  -H 'Authorization: Bearer change-this' \
  -H 'Content-Type: application/json' \
  -d '{"status":"completed"}'
```

## 11. Public proof gate

The local proof gate and the local pilot gate do not by themselves prove the public internet setup.

Use them to make the public claim honest before recording a proof video or widening outreach.

Check both the browser path and the plain HTTP path:

```bash
curl -I -L --max-redirs 2 https://pizza4people.com/
curl -I -L --max-redirs 2 https://pizza4people.com/press-kit/
curl -I -L --max-redirs 2 https://protocols4people.com/
curl -I -L --max-redirs 2 https://github.com/DennisHedegreen/p4p
```

```bash
google-chrome --headless=new --no-sandbox --disable-gpu --virtual-time-budget=8000 --dump-dom https://pizza4people.com/
google-chrome --headless=new --no-sandbox --disable-gpu --virtual-time-budget=8000 --dump-dom https://pizza4people.com/press-kit/
google-chrome --headless=new --no-sandbox --disable-gpu --virtual-time-budget=8000 --dump-dom https://protocols4people.com/
google-chrome --headless=new --no-sandbox --disable-gpu --virtual-time-budget=8000 --dump-dom https://hedegreenresearch.com/articles/nar-en-platform-forlader-markedet/
```

What to watch:

- browser-rendered DOM still shows the narrow claim: public protocol proof now, controlled live pilot next
- the press-kit HTML is reachable in both languages
- the companion article still matches the repo and proof-site wording
- anonymous GitHub access works
- if plain `curl` shows Simply `455` or another edge-layer difference while browser DOM still loads, log that honestly in `docs/PROOF-STATUS.md`
- if the hosted homepage copy differs from the locally generated `public/www/pizza4people/index.html`, treat that as upload drift and fix the host before broad outreach

## 12. How to read lab status

In `lab/`:

- `running` means subprocess exists
- `ready` means `/health` returned `200` with current registry registration

This distinction matters.

A node can be:

- `running` and `ready`
- `running` and `not ready`
- stopped entirely

Only the first state is truly green.

## 13. Common failure cases

### Port already in use

Symptom:

- service will not start

Fix:

- stop the old process
- or use another port for the lab

### Node never becomes ready

Symptom:

- node shows `running` but not `ready`

Check:

- primary and backup registries are actually running
- node health block shows failed registry details
- `P4P_REGISTRY_URLS` values are correct

### Discover works on primary but not backup

Symptom:

- failover claim is fake

Check:

- node was started with both registries in `P4P_REGISTRY_URLS`
- backup registry was running before or during node heartbeat cycles
- backup `/discover` really contains the node before primary shutdown

## 14. Minimum release confidence for v0.1

Before calling `v0.1` stable enough for demo, this should be true:

1. automated truthfulness tests are green
2. one-node manual flow works
3. closed-node rejection is confirmed
4. false-green test is confirmed
5. 10-node batch survives discovery failover from primary to backup
6. public browser pass is logged in `docs/PROOF-STATUS.md`

If one of those is missing, the system is not yet honest enough to present as proven.
