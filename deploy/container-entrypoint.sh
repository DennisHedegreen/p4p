#!/bin/sh
set -eu

service="${P4P_SERVICE:-}"
data_dir="${P4P_DATA_DIR:-/data}"
port="${PORT:-8000}"

case "$service" in
  registry|demo-node|pilot-node) ;;
  *)
    echo "P4P_SERVICE must be registry, demo-node, or pilot-node" >&2
    exit 64
    ;;
esac

case "$port" in
  ''|*[!0-9]*)
    echo "PORT must be numeric" >&2
    exit 64
    ;;
esac

if [ "$(id -u)" = "0" ]; then
  install -d -o p4p -g p4p -m 0700 "$data_dir"
  chown -R p4p:p4p "$data_dir"
  exec gosu p4p "$0" "$@"
fi

if [ ! -d "$data_dir" ] || [ ! -w "$data_dir" ]; then
  echo "P4P data directory is not writable: $data_dir" >&2
  exit 73
fi

case "$service" in
  registry)
    export P4P_REGISTRY_DB_PATH="${P4P_REGISTRY_DB_PATH:-$data_dir/registry.sqlite3}"
    export P4P_REGISTRY_KEY_FILE="${P4P_REGISTRY_KEY_FILE:-$data_dir/registry-key.json}"
    set -- python -m uvicorn --app-dir registry main:app --host 0.0.0.0 --port "$port"
    ;;
  demo-node)
    export P4P_NODE_KEY_FILE="${P4P_NODE_KEY_FILE:-$data_dir/demo-node-identity.json}"
    export P4P_NODE_ROOT_KEY_FILE="${P4P_NODE_ROOT_KEY_FILE:-$data_dir/demo-node-root.json}"
    set -- python -m uvicorn --app-dir demo-node demo_node:app --host 0.0.0.0 --port "$port"
    ;;
  pilot-node)
    export P4P_PILOT_NODE_DB_PATH="${P4P_PILOT_NODE_DB_PATH:-$data_dir/pilot-node.sqlite3}"
    export P4P_NODE_KEY_FILE="${P4P_NODE_KEY_FILE:-$data_dir/pilot-node-key.json}"
    set -- python -m uvicorn --app-dir pilot-node pilot_node:app --host 0.0.0.0 --port "$port"
    ;;
esac

exec "$@"
