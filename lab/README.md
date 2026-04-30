# P4P Lab

Separate local harness for testing the P4P protocol without polluting the protocol room itself.

This is not part of the protocol.

It is a browser control panel for:
- starting and stopping local registries
- starting and stopping many demo nodes
- watching service logs
- opening the client
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

## Notes

- `TEST-GUIDE.md` is the canonical rescue and proof sequence; `lab/README.md` is only the local harness quickstart.
- The panel expects the existing `registry/.venv` and `demo-node/.venv` runtimes to exist in the repo root.
- It starts subprocesses locally and captures their stdout logs.
- It can spawn many demo nodes with distinct ports and slightly shifted coordinates.
- Spawned demo nodes dual-register to both primary and backup registries by default.
- The panel distinguishes between a running node process and a ready node by probing `/health`.
- In lab terms, `running` means the subprocess still exists. `ready` means the node's `/health` endpoint returns `200` with current registry registration state.
- The lab serves the reference client directly at `http://127.0.0.1:8765/`, not under `/client/`.
