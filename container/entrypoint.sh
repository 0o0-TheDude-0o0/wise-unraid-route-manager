#!/bin/sh
set -eu

umask 077
mkdir -p /config/caddy /config/backups /config/tls /config/xdg/config /config/xdg/data /run/wise-route-manager

caddy_pid=
if [ "${WISE_EDITION:-full}" = "lite" ] && { [ ! -r /config/tls/tls.crt ] || [ ! -r /config/tls/tls.key ]; }; then
  echo "Wise Route Manager Lite: TLS files were not found; starting web admin only on port 9080." >&2
else
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
fi

cleanup() {
  if [ -n "$caddy_pid" ]; then
    kill "$caddy_pid" 2>/dev/null || true
    wait "$caddy_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

python3 -m app --config-dir /config --listen 0.0.0.0:9080 &
app_pid=$!
wait "$app_pid"
