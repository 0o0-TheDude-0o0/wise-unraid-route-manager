#!/bin/sh
set -eu

umask 077
mkdir -p /config/caddy /config/backups /config/tls /config/xdg/config /config/xdg/data /run/wise-route-manager

for tls_file in /config/tls/tls.crt /config/tls/tls.key; do
  if [ ! -r "$tls_file" ]; then
    echo "Required user-supplied TLS file is not readable: $tls_file" >&2
    exit 1
  fi
done

if [ ! -f /config/caddy/config.json ]; then
  cp /app/container/caddy.bootstrap.json /config/caddy/config.json
fi

caddy validate --config /config/caddy/config.json
caddy run --config /config/caddy/config.json &
caddy_pid=$!

cleanup() {
  kill "$caddy_pid" 2>/dev/null || true
  wait "$caddy_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

python3 -m app --config-dir /config --listen 0.0.0.0:9080 &
app_pid=$!
wait "$app_pid"
