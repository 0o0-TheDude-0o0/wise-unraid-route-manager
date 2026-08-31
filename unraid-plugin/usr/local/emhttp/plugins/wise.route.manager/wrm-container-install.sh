#!/bin/sh
set -eu

name=wise-route-manager-lite
image=${WISE_ROUTE_MANAGER_IMAGE:-ghcr.io/0o0-thedude-0o0/wise-unraid-route-manager:latest}
config_dir=/boot/config/plugins/wise.route.manager
cfg="$config_dir/wise.route.manager.cfg"

host_path=${1:?host appdata path is required}
ip_address=${2:?container IP address is required}
mount_mode=${3:-rw}
template_dir=/boot/config/plugins/dockerMan/templates-user
template_path="$template_dir/my-wise-route-manager-lite.xml"

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
  --label net.unraid.docker.managed=dockerman \
  --label net.unraid.docker.webui='http://[IP]:[PORT:9080]/' \
  --label net.unraid.docker.icon='https://raw.githubusercontent.com/0o0-TheDude-0o0/wise-unraid-route-manager/main/docs/wise-route-manager-icon.svg' \
  --network br0 \
  --ip "$ip_address" \
  -v "$host_path:/config:$mount_mode" \
  -e WISE_EDITION=lite \
  -e WISE_MASTER_KEY_FILE=/config/master.key \
  -e WISE_ENABLE_PROVIDER_MUTATIONS=0 \
  -e WISE_CERT_RENEWAL_INTERVAL_SECONDS=21600 \
  "$image" >/dev/null

# Give DockerMan an editable, first-party-style template for future changes.
# Do not overwrite it after the first creation: users may intentionally edit it.
if [ ! -f "$template_path" ]; then
  mkdir -p "$template_dir"
  cat > "$template_path" <<EOF
<?xml version="1.0"?>
<Container version="2">
  <Name>Wise Route Manager Lite</Name>
  <Repository>$image</Repository>
  <Registry>https://github.com/0o0-TheDude-0o0/wise-unraid-route-manager/pkgs/container/wise-unraid-route-manager</Registry>
  <Network>br0</Network>
  <MyIP>$ip_address</MyIP>
  <Shell>sh</Shell>
  <Privileged>false</Privileged>
  <Support>https://github.com/0o0-TheDude-0o0/wise-unraid-route-manager/issues</Support>
  <Project>https://github.com/0o0-TheDude-0o0/wise-unraid-route-manager</Project>
  <Overview>Wise Route Manager Lite provides a safe, read-only-first workspace for discovering, auditing, and reviewing LAN route changes.</Overview>
  <Category>Network:Other</Category>
  <WebUI>http://[IP]:[PORT:9080]/</WebUI>
  <Config Name="Appdata" Target="/config" Default="$host_path" Mode="$mount_mode" Description="Wise Route Manager Lite data. Keep Read/Write - Slave when this path is on an unassigned SSD." Type="Path" Display="always" Required="true" Mask="false" />
  <Config Name="Edition" Target="WISE_EDITION" Default="lite" Description="Keep lite for the Lite edition." Type="Variable" Display="advanced" Required="true" Mask="false" />
  <Config Name="Master key path" Target="WISE_MASTER_KEY_FILE" Default="/config/master.key" Description="Keep the encryption key inside the persistent appdata mapping." Type="Variable" Display="advanced" Required="true" Mask="false" />
  <Config Name="Enable live changes" Target="WISE_ENABLE_PROVIDER_MUTATIONS" Default="0" Description="Keep 0 until discovery and the first preview are verified." Type="Variable" Display="advanced" Required="true" Mask="false" />
  <Config Name="Management UI" Target="9080" Default="9080" Mode="tcp" Description="Authenticated Route Manager Lite web interface." Type="Port" Display="always" Required="true" Mask="false" />
</Container>
EOF
  chmod 0644 "$template_path" 2>/dev/null || true
fi

tmp=$(mktemp)
grep -v '^APP_URL=' "$cfg" 2>/dev/null > "$tmp" || true
printf 'APP_URL="http://%s:9080"\n' "$ip_address" >> "$tmp"
cat "$tmp" > "$cfg"
rm -f "$tmp"
chmod 0600 "$cfg" 2>/dev/null || true

printf 'Wise Route Manager Lite is running at http://%s:9080\n' "$ip_address"
