#!/bin/sh
set -eu

config_dir=/boot/config/plugins/wise.route.manager
sources="/var/local/emhttp/var.ini /boot/config/docker.cfg /boot/config/plugins/dockerMan/docker.cfg"

# Emit every appdata-shaped path found in Docker settings and user templates.
emit_config_value() {
  key=$1
  for source in $sources; do
    [ -r "$source" ] || continue
    awk -F'"' -v key="$key" '$0 ~ "^" key "=" { if (NF >= 2) print $2; else { sub("^[^=]*=", ""); print } }' "$source"
  done
}

{
  emit_config_value DOCKER_APP_CONFIG_PATH
  emit_config_value DOCKER_APPDATA
  for template in /boot/config/plugins/dockerMan/templates-user/my-*.xml; do
    [ -f "$template" ] || continue
    grep -oE '/mnt/[^"< >]*/appdata([^"< >]*)' "$template" || true
  done

  # Include live bind mounts, which catches containers created outside templates.
  if command -v docker >/dev/null 2>&1; then
    for container in $(docker ps -aq 2>/dev/null || true); do
      docker inspect --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' "$container" 2>/dev/null || true
    done
  fi
} | grep -oE '/mnt/[^"[:space:]]*/appdata([^"[:space:]]*)?' | sed 's#\(/appdata\)/.*#\1/#; s#/$#/#' | sort | uniq -c | while read -r references root; do
  [ -n "$root" ] || continue
  root=${root%/}/
  mode="Read/Write"
  kind="Unraid user share"
  case "$root" in
    /mnt/disks/*)
      mode="Read/Write - Slave"
      kind="Unassigned disk"
      ;;
    /mnt/cache/*|/mnt/*/*pool*/appdata/)
      kind="Cache/pool"
      ;;
  esac
  source=$(findmnt -T "$root" -no SOURCE 2>/dev/null || true)
  # findmnt may append a subvolume or bind-mount selector in brackets.
  source=${source%%[*}
  filesystem=$(findmnt -T "$root" -no FSTYPE 2>/dev/null || true)
  drive="unknown drive"
  rota=$(lsblk -ndo ROTA "$source" 2>/dev/null || true)
  if [ "$rota" = "0" ]; then drive="SSD"; elif [ "$rota" = "1" ]; then drive="HDD"; fi
  configured="no"
  configured_path=$(emit_config_value DOCKER_APP_CONFIG_PATH | head -n 1 || true)
  case "${configured_path%/}/" in "$root") configured="yes" ;; esac
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$root" "$kind" "$drive" "$filesystem" "$mode" "$references:$configured"
done
