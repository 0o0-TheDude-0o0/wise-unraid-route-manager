#!/bin/sh
set -eu

name=wise-route-manager-lite
image=${WISE_ROUTE_MANAGER_IMAGE:-ghcr.io/0o0-thedude-0o0/wise-unraid-route-manager:latest}
config_dir=/boot/config/plugins/wise.route.manager
cfg="$config_dir/wise.route.manager.cfg"

host_path=${1:?host appdata path is required}
ip_address=${2:?container IP address is required}
mount_mode=${3:-rw}

case "$host_path" in
  /mnt/*) ;;
  *) echo "Host path must be under /mnt." >&2; exit 2 ;;
esac
case "$host_path" in *'
'*|*'	'*|*..* ) echo "Host path contains unsupported characters." >&2; exit 2;; esac
case "$ip_address" in
  *[!0-9.]*|*.*.*.*.*|'' ) echo "Container IP must be an IPv4 address." >&2; exit 2 ;;
esac
case "$mount_mode" in
  rw|rw,slave) ;;
  *) echo "Mount mode must be rw or rw,slave." >&2; exit 2 ;;
esac

mkdir -p "$config_dir" "$host_path"
[ -f "$cfg" ] || printf '%s\n' 'APP_URL=""' > "$cfg"
chmod 0600 "$cfg" 2>/dev/null || true

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not available on this Unraid host." >&2
  exit 1
fi

docker pull "$image"
if docker inspect "$name" >/dev/null 2>&1; then
  echo "Updating existing $name container while preserving appdata at $host_path."
  docker rm -f "$name" >/dev/null
fi
docker run -d \
  --name "$name" \
  --restart unless-stopped \
  --network br0 \
  --ip "$ip_address" \
  -v "$host_path:/config:$mount_mode" \
  -e WISE_EDITION=lite \
  -e WISE_MASTER_KEY_FILE=/config/master.key \
  -e WISE_ENABLE_PROVIDER_MUTATIONS=0 \
  -e WISE_CERT_RENEWAL_INTERVAL_SECONDS=21600 \
  "$image" >/dev/null

tmp=$(mktemp)
grep -v '^APP_URL=' "$cfg" 2>/dev/null > "$tmp" || true
printf 'APP_URL="http://%s:9080"\n' "$ip_address" >> "$tmp"
cat "$tmp" > "$cfg"
rm -f "$tmp"
chmod 0600 "$cfg" 2>/dev/null || true

printf 'Wise Route Manager Lite is running at http://%s:9080\n' "$ip_address"
