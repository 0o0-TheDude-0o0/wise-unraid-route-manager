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
for source in /var/local/emhttp/var.ini /boot/config/docker.cfg /boot/config/plugins/dockerMan/docker.cfg; do
  if [ -r "$source" ]; then
    value=$(sed -n -n 's/^[[:space:]]*DOCKER_APPDATA[[:space:]]*=[[:space:]]*"\{0,1\}\([^"[:space:]]*\)"\{0,1\}.*/\1/p' "$source" | head -n 1)
    if [ -n "$value" ]; then
      default_appdata=$value
      break
    fi
  fi
done
if [ -n "$default_appdata" ]; then
  umask 077
  if grep -q '^DEFAULT_APPDATA=' "$config_dir/wise.route.manager.cfg" 2>/dev/null; then
    sed -i "s|^DEFAULT_APPDATA=.*|DEFAULT_APPDATA=\"$default_appdata\"|" "$config_dir/wise.route.manager.cfg"
  else
    printf 'DEFAULT_APPDATA="%s"\n' "$default_appdata" >> "$config_dir/wise.route.manager.cfg"
  fi
fi
