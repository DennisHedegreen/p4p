#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
image="p4p-host-candidate:local"
suffix="$$"
network="p4p-container-check-$suffix"
registry_a="p4p-registry-a-$suffix"
registry_b="p4p-registry-b-$suffix"
demo="p4p-demo-$suffix"
runtime_root="$(mktemp -d -t p4p-container-check-XXXXXX)"

cleanup() {
  docker rm -f "$demo" "$registry_a" "$registry_b" >/dev/null 2>&1 || true
  docker network rm "$network" >/dev/null 2>&1 || true
  docker run --rm \
    --user 0:0 \
    --volume "$runtime_root:/runtime" \
    --env "HOST_UID=$(id -u)" \
    --env "HOST_GID=$(id -g)" \
    --entrypoint /bin/sh \
    "$image" \
    -c 'chown -R "$HOST_UID:$HOST_GID" /runtime && chmod -R u+rwX /runtime' >/dev/null 2>&1 || true
  rm -rf "$runtime_root"
}
trap cleanup EXIT

wait_for_json() {
  local url="$1"
  local attempts=60
  while ! curl --fail --silent --show-error --max-time 2 "$url" >/dev/null 2>&1; do
    attempts=$((attempts - 1))
    if [ "$attempts" -le 0 ]; then
      echo "Timed out waiting for $url" >&2
      return 1
    fi
    sleep 0.5
  done
}

start_registry() {
  local name="$1"
  local host_port="$2"
  local advertised_url="$3"
  local state_dir="$4"
  docker run --detach --rm \
    --user 0:0 \
    --name "$name" \
    --network "$network" \
    --publish "127.0.0.1:$host_port:8000" \
    --volume "$state_dir:/data" \
    --env P4P_SERVICE=registry \
    --env PORT=8000 \
    --env "P4P_REGISTRY_URL=$advertised_url" \
    --env P4P_REGISTRY_ADMIN_TOKEN=container-check-admin-token-with-enough-entropy \
    --env P4P_CORS_ORIGINS=http://127.0.0.1:8768 \
    "$image" >/dev/null
}

mkdir -p "$runtime_root/registry-a" "$runtime_root/registry-b" "$runtime_root/demo"

docker build --tag "$image" "$root"
docker network create "$network" >/dev/null

start_registry "$registry_a" 18000 http://127.0.0.1:18000 "$runtime_root/registry-a"
start_registry "$registry_b" 18002 http://127.0.0.1:18002 "$runtime_root/registry-b"

wait_for_json http://127.0.0.1:18000/health
wait_for_json http://127.0.0.1:18002/health

docker run --detach --rm \
  --user 0:0 \
  --name "$demo" \
  --network "$network" \
  --publish 127.0.0.1:18101:8101 \
  --volume "$runtime_root/demo:/data" \
  --env P4P_SERVICE=demo-node \
  --env PORT=8101 \
  --env P4P_REGISTRY_URLS="http://$registry_a:8000,http://$registry_b:8000" \
  --env P4P_NODE_BASE_URL=http://127.0.0.1:18101 \
  --env P4P_NODE_ID=dk-container-proof-001 \
  --env 'P4P_NODE_NAME=P4P Container Proof' \
  --env P4P_NODE_CITY=Brondby \
  --env P4P_NODE_COUNTRY=DK \
  --env P4P_NODE_CATEGORIES=pizza \
  --env P4P_NODE_ORDER_MODE=test \
  --env P4P_OPERATOR_ENABLED=false \
  "$image" >/dev/null

wait_for_json http://127.0.0.1:18101/p4p/menu

python3 - <<'PY'
import json
import time
import urllib.parse
import urllib.request
query = urllib.parse.urlencode(
    {"lat": 55.6517, "lng": 12.4126, "radius": 10, "category": "pizza", "country": "DK"}
)

def read_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=3) as response:
        return json.load(response)

for _ in range(60):
    payloads = [
        read_json(f"http://127.0.0.1:{port}/discover?{query}")
        for port in (18000, 18002)
    ]
    if all(any(node["node_id"] == "dk-container-proof-001" for node in payload["nodes"]) for payload in payloads):
        break
    time.sleep(0.5)
else:
    raise SystemExit("container node did not become discoverable through both registries")

for port in (18000, 18002):
    info = read_json(f"http://127.0.0.1:{port}/health")
    if info["storage_backend"] != "sqlite" or not info["registry_signing_enabled"]:
        raise SystemExit(f"registry {port} is not persistent and signed")

PY

for container in "$registry_a" "$registry_b" "$demo"; do
  docker exec "$container" /bin/sh -c \
    'awk '\''/^Uid:/ {exit !($2 == 10001)}'\'' /proc/1/status'
  if docker exec "$container" /bin/sh -c \
    'find /data -type f ! -perm 0600 -print -quit | grep -q .'; then
    echo "Runtime file is not mode 0600 in $container" >&2
    exit 1
  fi
done

docker rm -f "$demo" >/dev/null
docker rm -f "$registry_a" "$registry_b" >/dev/null

start_registry "$registry_a" 18000 http://127.0.0.1:18000 "$runtime_root/registry-a"
start_registry "$registry_b" 18002 http://127.0.0.1:18002 "$runtime_root/registry-b"
wait_for_json http://127.0.0.1:18000/health
wait_for_json http://127.0.0.1:18002/health

python3 - <<'PY'
import json
import urllib.parse
import urllib.request

query = urllib.parse.urlencode(
    {"lat": 55.6517, "lng": 12.4126, "radius": 10, "category": "pizza", "country": "DK"}
)
for port in (18000, 18002):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/discover?{query}", timeout=3) as response:
        nodes = json.load(response)["nodes"]
    if not any(node["node_id"] == "dk-container-proof-001" for node in nodes):
        raise SystemExit(f"registry {port} lost its node across restart")
PY

echo "P4P container candidate is green."
