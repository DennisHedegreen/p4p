# node-control

Local multi-node control plane for the first P4P pilot fleet.

This is not a registry feature.

It is also not a protocol module.

It is a separate local operator/admin surface that reads:

- registry source truth
- public node health
- optional node operator state
- optional node module state

The point is to let one person watch several restaurant-owned nodes without turning the registry into the admin boss.

## What It Does

- lists nodes seen by one or more registries
- shows which registries currently see each node
- shows public node readiness and order mode
- shows optional operator-backed module detail when a token is configured
- shows optional operator-backed hardware-profile detail when a token is configured
- shows active payment lane and module health for the selected node

## What It Must Not Become

- the registry's hidden control panel
- the place that owns restaurant menu or order data
- a backdoor to broaden registry authority

The registry lists node state.

The node still owns node state.

This surface only reads and aggregates.

## Local Run

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
P4P_NODE_CONTROL_REGISTRY_URLS=http://127.0.0.1:8000,http://127.0.0.1:8002 \
P4P_NODE_CONTROL_OPERATOR_TOKENS='{"dk-brondby-kebab-001":"operator-secret"}' \
./.venv/bin/uvicorn node_control:app --port 8210
```

Then open:

- `http://127.0.0.1:8210/`

## Runtime Config

- `P4P_NODE_CONTROL_REGISTRY_URLS` is the comma-separated list of registries to read.
- `P4P_NODE_CONTROL_OPERATOR_TOKENS` is a JSON object keyed by `node_id` or exact node endpoint, used only for optional `/operator/state` and `/operator/modules` reads.
- `P4P_NODE_CONTROL_TIMEOUT_SECONDS` controls per-request probe timeout.

## Endpoints

- `GET /`
- `GET /health`
- `GET /api/overview`
- `GET /api/nodes/{node_id}`
