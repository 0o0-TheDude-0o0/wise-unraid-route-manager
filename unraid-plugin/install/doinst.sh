#!/bin/sh
set -eu

config_dir=/boot/config/plugins/wise.route.manager
mkdir -p "$config_dir"
if [ ! -f "$config_dir/wise.route.manager.cfg" ]; then
  printf '%s\n' 'APP_URL=""' > "$config_dir/wise.route.manager.cfg"
  chmod 0600 "$config_dir/wise.route.manager.cfg"
fi

# Preserve Unraid's current Docker appdata preference for webGUI guidance.
# Templates intentionally leave their host path blank so Unraid can apply its
# own default for each installation.
default_appdata=""
docker_dir=""
for source in /var/local/emhttp/var.ini /boot/config/docker.cfg /boot/config/plugins/dockerMan/docker.cfg; do
  if [ -r "$source" ]; then
    value=$(grep -oE '(DOCKER_APPDATA|DOCKER_APPDATA_PATH|DOCKER_DEFAULT_APPDATA)[[:space:]]*=[[:space:]]*"?[^"[:space:]]+' "$source" 2>/dev/null | sed -n 's/.*=[[:space:]]*"\{0,1\}//p' | head -n 1)
    if [ -n "$value" ]; then
      default_appdata=$value
      break
    fi
    value=$(grep -oE 'DOCKER_DIR[[:space:]]*=[[:space:]]*"?[^"[:space:]]+' "$source" 2>/dev/null | sed -n 's/.*=[[:space:]]*"\{0,1\}//p' | head -n 1)
    if [ -n "$value" ] && [ -z "$docker_dir" ]; then docker_dir=$value; fi
  fi
done
if [ -z "$default_appdata" ]; then
  default_appdata=$(grep -hoE '/mnt/(disks|cache|user)/[^"[:space:]]*/appdata/?' /var/local/emhttp/var.ini /boot/config/docker.cfg /boot/config/plugins/dockerMan/docker.cfg 2>/dev/null | head -n 1 || true)
fi
# Some Unraid versions persist only DOCKER_DIR. When it points into a sibling
# DockerImage/docker directory, infer the configured appdata directory beside it.
if [ -z "$default_appdata" ] && [ -n "$docker_dir" ]; then
  case "$docker_dir" in
    /mnt/*/DockerImage/docker|/mnt/*/DockerImage/docker/)
      default_appdata=${docker_dir%/DockerImage/docker*}/appdata/ ;;
  esac
fi
if [ -n "$default_appdata" ]; then
  default_appdata=${default_appdata%/}/
  appdata_mode="rw"
  drive_type="Unraid user share"
  case "$default_appdata" in
    /mnt/disks/*)
      appdata_mode="rw,slave"
      device=$(findmnt -T "$default_appdata" -no SOURCE 2>/dev/null || true)
      rota=$(lsblk -ndo ROTA "$device" 2>/dev/null || true)
      if [ "$rota" = "0" ]; then drive_type="unassigned SSD"; else drive_type="unassigned drive"; fi
      ;;
    /mnt/cache/*) drive_type="cache/pool path" ;;
  esac
  umask 077
  for setting in DEFAULT_APPDATA APPDATA_MOUNT_MODE APPDATA_DRIVE_TYPE; do sed -i "/^${setting}=/d" "$config_dir/wise.route.manager.cfg"; done
  printf 'DEFAULT_APPDATA="%s"\nAPPDATA_MOUNT_MODE="%s"\nAPPDATA_DRIVE_TYPE="%s"\n' "$default_appdata" "$appdata_mode" "$drive_type" >> "$config_dir/wise.route.manager.cfg"
fi
