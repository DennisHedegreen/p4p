# demo-node

Canonical `v0.1` demo restaurant node.

Responsibilities:
- announce itself to one or more registries
- sign announcements and heartbeats with an Ed25519 node key
- send heartbeat every 60 seconds
- serve `GET /menu`
- accept `POST /order`
- print received orders in the terminal

Target:
Minimal Python service used to prove the protocol loop.

## Files

- `demo_node.py` — FastAPI node with announce/heartbeat loop
- `operator.html` — local reference node-operator UI
- `requirements.txt` — minimal runtime dependencies

## Local run

```bash
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
P4P_REGISTRY_URLS=http://127.0.0.1:8000,http://127.0.0.1:8002 \
P4P_NODE_BASE_URL=http://127.0.0.1:8001 \
./.venv/bin/uvicorn demo_node:app --reload --port 8001
```

Runtime config:

- `P4P_REGISTRY_URLS` is the canonical failover input. Use a comma-separated list of full registry base URLs.
- `P4P_REGISTRY_URL` remains supported as a backward-compatible single-registry fallback.
- `P4P_NODE_BASE_URL` may use loopback HTTP for local reference development only. Public-facing nodes should expose HTTPS.
- `P4P_NODE_ORDER_MODE` controls order intake. Supported values: `disabled`, `menu_only`, `test`, `live`. The demo default is `test`.
- `P4P_NODE_KEY_FILE` persists the generated Ed25519 private key in a JSON file.
- `P4P_NODE_PRIVATE_KEY` can provide an existing `ed25519:` private key directly.
- `P4P_NODE_ROOT_KEY_FILE` persists an optional root identity key used to sign delegation for the operational node key.
- `P4P_NODE_ROOT_PRIVATE_KEY` can provide that root identity key directly.
- `P4P_NODE_DELEGATION_ROLE` controls delegated role metadata: `primary` or `backup`.
- `P4P_NODE_DELEGATION_CAPABILITIES` controls the delegated registry capabilities, currently `announce` and/or `heartbeat`.
- `P4P_NODE_DELEGATION_ISSUED_AT` and `P4P_NODE_DELEGATION_EXPIRES_AT` can pin delegation timing explicitly.
- `P4P_NODE_MANIFEST_VERSION` controls the root-signed node-manifest version posted to registries when a root key exists.
- `P4P_NODE_MANIFEST_ISSUED_AT`, `P4P_NODE_MANIFEST_KEY_STATUS`, and `P4P_NODE_MANIFEST_KEY_EXPIRES_AT` can pin manifest timing and key lifecycle explicitly.
- `P4P_OPERATOR_ENABLED=false` disables the demo operator endpoints for public proof deployments.

If neither key setting is provided, the demo node generates an ephemeral key at startup.

Use a persistent key for any node whose `node_id` should survive process restarts.

If no root key is configured, the node still works with direct node-owned identity only.

If a root key is configured, the demo node publishes a root-signed node manifest to registries before announce calls. That lets registries enforce revocation and root rotation for that `node_id`.

## Endpoints

- `GET /health` — readiness signal, `200` only when at least one configured registry has a current successful announce or heartbeat cycle. Returns `503` when the process is up but registration is absent or stale.
- `GET /operator` — reference node-operator UI. Demo-only; disable with `P4P_OPERATOR_ENABLED=false` for public proof deployments.
- `GET /operator/state`
- `POST /operator/state` — updates `open`, `order_mode`, and `modules`, then reannounces the node.
- `POST /operator/reannounce`
- `GET /p4p/menu`
- `POST /p4p/order` — accepts only when `P4P_NODE_ORDER_MODE` is `test` or `live`.
- `GET /p4p/info`
