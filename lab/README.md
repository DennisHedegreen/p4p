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

## Run

```bash
cd /path/to/p4p/lab
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
./.venv/bin/uvicorn app:app --reload --port 8899
```

Open:

`http://127.0.0.1:8899`

## Scenario Config

The main GUI is driven by `lab/scenarios.json`.

That file declares:

- service name
- working directory
- command argv
- environment variables
- health URL
- links with short explanations
- scenarios that group services together

The GUI should not need code changes when adding a local test command. Add a
service or scenario to `lab/scenarios.json`, restart or refresh the lab, and the
new button/link/command appears in the browser.

Current configured scenarios:

- `pilot-photo-map-menu`: starts the pilot node with `p4p.catalog.editor`,
  `p4p.menu.photo-map`, `p4p.menu.list`, `p4p.customer.status`, and
  `p4p.payment.cash`.
- `registry-client-demo-node`: starts primary registry, backup registry, the
  static client, and one demo node for the classic local proof.

## Notes

- `TEST-GUIDE.md` is the canonical rescue and proof sequence; `lab/README.md` is only the local harness quickstart.
- The panel expects the existing `registry/.venv` and `demo-node/.venv` runtimes to exist in the repo root.
- The configured pilot-node scenario expects `pilot-node/.venv` to exist.
- It starts subprocesses locally and captures their stdout logs.
- It can spawn many demo nodes with distinct ports and slightly shifted coordinates.
- Spawned demo nodes dual-register to both primary and backup registries by default.
- The panel distinguishes between a running node process and a ready node by probing `/health`.
- In lab terms, `running` means the subprocess still exists. `ready` means the node's `/health` endpoint returns `200` with current registry registration state.
- The lab serves the reference client directly at `http://127.0.0.1:8765/`, not under `/client/`.
