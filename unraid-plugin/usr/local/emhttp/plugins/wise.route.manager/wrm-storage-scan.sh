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

storage_probe_path() {
  path=${1%/}
  case "$path" in
    /mnt/disks/*/*) printf '/mnt/disks/%s\n' "$(printf '%s\n' "${path#/mnt/disks/}" | cut -d/ -f1)" ;;
    *) printf '%s\n' "$path" ;;
  esac
}

drive_type_for_source() {
  device=$1
  device=${device%%[*}
  [ -n "$device" ] || return 0
  rota=$(lsblk -ndo ROTA "$device" 2>/dev/null | head -n 1 || true)
  if [ -z "$rota" ] && [ "${device#/dev/}" != "$device" ]; then
    parent=$(lsblk -ndo PKNAME "$device" 2>/dev/null | head -n 1 || true)
    [ -n "$parent" ] && rota=$(lsblk -ndo ROTA "/dev/$parent" 2>/dev/null | head -n 1 || true)
  fi
  if [ "$rota" = "0" ]; then printf 'SSD\n'; elif [ "$rota" = "1" ]; then printf 'HDD\n'; fi
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
} | grep -oE '/mnt/[^"[:space:]]*/appdata([^"[:space:]]*)?' | awk '
  {
    original=$0
    gsub(/[`.,;:)\]}]+$/, "", original)
    root=$0
    gsub(/[`.,;:)\]}]+$/, "", root)
    sub(/\/appdata\/.*/, "/appdata/", root)
    sub(/\/?$/, "/", root)
    references[root]++
    path_key=root SUBSEP original
    if (!seen[path_key]++) {
      paths[root]=(paths[root] ? paths[root] "|" original : original)
    }
  }
  END {
    for (root in references) {
      printf "%s\t%s\t%s\n", references[root], root, paths[root]
    }
  }
' | sort -k2,2 | while IFS="$(printf '\t')" read -r references root found_paths; do
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
  probe=$(storage_probe_path "$root")
  source=$(findmnt -T "$root" -no SOURCE 2>/dev/null || findmnt -T "$probe" -no SOURCE 2>/dev/null || true)
  filesystem=$(findmnt -T "$root" -no FSTYPE 2>/dev/null || findmnt -T "$probe" -no FSTYPE 2>/dev/null || true)
  drive="No single device"
  resolved_drive=$(drive_type_for_source "$source")
  [ -n "$resolved_drive" ] && drive=$resolved_drive
  case "$root" in
    /mnt/user/*)
      drive="User share"
      [ -n "$filesystem" ] || filesystem="fuse.shfs"
      ;;
    /mnt/cache/*)
      [ "$drive" = "No single device" ] && drive="Pool/share managed"
      [ -n "$filesystem" ] || filesystem="Pool/share managed"
      ;;
  esac
  configured="no"
  configured_path=$(emit_config_value DOCKER_APP_CONFIG_PATH | head -n 1 || true)
  case "${configured_path%/}/" in "$root") configured="yes" ;; esac
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$root" "$kind" "$drive" "$filesystem" "$mode" "$references:$configured" "$found_paths"
done
