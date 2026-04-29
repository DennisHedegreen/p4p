# P4P Deploy Notes

This is the minimal server shape for the public proof and the first controlled live pilot.

The demo-node proof is not for live restaurant orders.

The live pilot must use `pilot-node/`.

## Services

For the public proof, run four public surfaces:

- public site: static files from `../public/www/pizza4people`
- protocol client: static files from `client/`
- primary registry: FastAPI registry
- backup registry: FastAPI registry
- demo node: FastAPI demo node with `order_mode=test`

For the first live pilot, run:

- public site: static files from `../public/www/pizza4people`
- protocol client: static files from `client/`
- primary registry: FastAPI registry on Hetzner
- backup registry: FastAPI registry on Dennis' own server
- restaurant node: FastAPI pilot node, owned or controlled by the restaurant

Recommended public host names:

- `client.pizza4people.com`
- `registry-a.pizza4people.com`
- `registry-b.pizza4people.com`
- `demo-node.pizza4people.com`
- `node.example-restaurant.dk`

HTTPS is required for public node and registry URLs.

The demo node operator UI must be disabled on the public proof with:

```bash
P4P_OPERATOR_ENABLED=false
```

## Minimal Runtime

Use Python 3.12 or newer.

Install dependencies separately in each service folder:

```bash
cd registry
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

cd ../demo-node
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt

cd ../pilot-node
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
```

Serve `../public/www/pizza4people` as the public Pizza4People site.

Serve `client/` separately as the protocol client when exposing the interactive proof or pilot ordering flow.

## Environment Files

Use the example files in this folder as templates:

- `primary-registry.env.example`
- `backup-registry.env.example`
- `demo-node.env.example`
- `pilot-node.env.example`
- `client-config.public.example.js`
- `p4p-registry.service.example`
- `p4p-pilot-node.service.example`
- `caddy.live-pilot.example`

Do not commit real private node keys or server secrets.

For public registries, set a writable SQLite path in each registry env file:

```bash
P4P_REGISTRY_DB_PATH=/var/lib/p4p/registry-a.sqlite3
```

Use separate files per registry process.

If you want signed `GET /registry-source` snapshots, also give each registry a stable signing key file:

```bash
P4P_REGISTRY_KEY_FILE=/var/lib/p4p/registry-a-key.json
```

Do not share the same registry signing key between separate registry hosts.

If a registry should automatically mirror another registry, also configure:

```bash
P4P_REGISTRY_METADATA='{"registry_type":"country","capabilities":{"can_onboard_nodes":true,"can_relay_sources":true,"can_curate_active_index":true,"can_reexport_sources":false},"scope":{"vertical_id":"pizza4people","country_code":"DK"}}'
P4P_MIRROR_UPSTREAMS=https://registry-a.pizza4people.com
P4P_MIRROR_TRUSTED_UPSTREAMS=https://registry-a.pizza4people.com
P4P_MIRROR_DISCOVERY_POLICY=trusted_only
P4P_CURATED_INDEX_PROMOTION_POLICY=trusted_mirrors
P4P_REGISTRY_SOURCE_REEXPORT_POLICY=local_plus_trusted_mirrors
P4P_MIRROR_SYNC_INTERVAL_SECONDS=60
P4P_MIRROR_SOURCE_TTL_SECONDS=600
```

If `P4P_MIRROR_DISCOVERY_POLICY` is omitted, the runtime defaults to `trusted_only` when upstream or trusted-source config exists and falls back to `all_active` only for blank local-dev mirrors.

`P4P_REGISTRY_SOURCE_REEXPORT_POLICY=local_plus_trusted_mirrors` is only for scoped umbrella or country registries that should relay trusted upstream snapshots onward. It does not turn mirrored cache into new local source-of-record data.

`P4P_CURATED_INDEX_PROMOTION_POLICY=trusted_mirrors` allows explicit policy promotion from raw mirror cache into the curated active index. Without that setting, imported snapshots remain raw evidence and stay out of `GET /discover`.

Capability gates are enforced by `P4P_REGISTRY_METADATA`:

- `can_onboard_nodes` for `POST /announce`
- `can_relay_sources` for `POST /registry-source/import` and sync
- `can_curate_active_index` for promotion into discoverable mirrored state
- `can_reexport_sources` for `GET /registry-source` when re-exporting trusted mirrors

Do not point the public proof registries at each other unless you explicitly want mirrored discovery behavior.

## Live Pilot Runtime Rules

Use `pilot-node/` for live restaurant orders.

Do not expose the demo node as a live restaurant.

Store runtime files outside the repo:

```bash
sudo install -d -o p4p -g p4p /var/lib/p4p
sudo install -d -o root -g root /etc/p4p
```

Required live pilot files:

- `/etc/p4p/registry.env` for each registry host
- `/etc/p4p/pilot-node.env` for the restaurant node host
- `/var/lib/p4p/*.sqlite3` for persistent data
- `/var/lib/p4p/*-key.json` for node or registry signing keys

Set env files to owner-readable only because `pilot-node.env` contains the operator token:

```bash
sudo chmod 600 /etc/p4p/*.env
```

Start with:

```bash
P4P_NODE_ORDER_MODE=menu_only
```

Switch to:

```bash
P4P_NODE_ORDER_MODE=live
```

only after the restaurant has confirmed that it can see, accept, reject, mark ready, complete, and cancel orders.

If the restaurant node is hosted by Dennis during the first pilot, document it as a hosted restaurant node. Do not describe it as full restaurant self-hosting.

## Systemd Shape

Copy and adjust:

- `p4p-registry.service.example` for registry A and registry B
- `p4p-pilot-node.service.example` for the restaurant node

Use different ports per process when more than one service runs on the same machine.

Example:

- registry A: `127.0.0.1:8000`
- registry B: `127.0.0.1:8002`
- pilot node: `127.0.0.1:8201`

Use Caddy or nginx as the public HTTPS reverse proxy.

`caddy.live-pilot.example` shows the intended host-to-local-port mapping.

## Proof Smoke

After the services are running:

```bash
curl https://registry-a.pizza4people.com/registry-info
curl https://registry-a.pizza4people.com/identity-log
curl "https://registry-a.pizza4people.com/discover?lat=55.6517&lng=12.4126&radius=10&category=pizza&country=DK"
curl "https://registry-a.pizza4people.com/directory?lat=55.6517&lng=12.4126&radius=10&category=pizza&country=DK"
curl https://demo-node.pizza4people.com/p4p/menu
curl https://registry-a.pizza4people.com/curated-overrides
```

Then stop or block the primary registry and verify discovery through the backup:

```bash
curl "https://registry-b.pizza4people.com/discover?lat=55.6517&lng=12.4126&radius=10&category=pizza&country=DK"
curl https://registry-b.pizza4people.com/curated-promotions
```

The proof is ready to record only when:

- both registries return the demo node
- `/identity-log` contains a signed record
- menu comes directly from the demo node
- test order goes directly to the demo node
- backup discovery still works after primary failure
- `https://demo-node.pizza4people.com/operator` is not publicly available

## Live Pilot Smoke

Before a real customer uses the system:

```bash
curl https://registry-a.pizza4people.com/registry-info
curl https://registry-b.pizza4people.com/registry-info
curl "https://registry-a.pizza4people.com/discover?lat=55.6517&lng=12.4126&radius=10&category=kebab&country=DK"
curl "https://registry-b.pizza4people.com/discover?lat=55.6517&lng=12.4126&radius=10&category=kebab&country=DK"
curl https://node.example-restaurant.dk/health
curl https://node.example-restaurant.dk/p4p/menu
```

Then test operator access from a trusted machine:

```bash
curl -H "Authorization: Bearer $P4P_OPERATOR_TOKEN" https://node.example-restaurant.dk/operator/state
curl -H "Authorization: Bearer $P4P_OPERATOR_TOKEN" https://node.example-restaurant.dk/operator/orders
```

Do not send a real live order until:

- the node is visible through both registries
- the client fetches the menu directly from the node
- the restaurant can see orders in `/operator/orders`
- `open=false` and `order_mode=menu_only` both stop order intake immediately
- primary registry failure still leaves backup discovery working
