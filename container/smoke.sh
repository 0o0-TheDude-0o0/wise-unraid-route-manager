#!/bin/sh
set -eu

[ "$(id -u)" = "1000" ] || {
  echo "container is not running as UID 1000" >&2
  exit 1
}

python3 /app/container/generate-smoke-cert.py

/app/container/entrypoint.sh &
entrypoint_pid=$!
cleanup() {
  kill "$entrypoint_pid" 2>/dev/null || true
  wait "$entrypoint_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

attempt=0
while [ "$attempt" -lt 40 ]; do
  if response=$(python3 -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9080/healthz', timeout=1).read().decode())" 2>/dev/null); then
    python3 -c "import socket,ssl; context=ssl._create_unverified_context(); connection=context.wrap_socket(socket.create_connection(('127.0.0.1',443),timeout=2),server_hostname='app.example.test'); print('tls='+connection.version()); connection.close()"
    echo "$response"
    echo "container_uid=$(id -u)"
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 0.25
done

echo "health endpoint did not become ready" >&2
exit 1
