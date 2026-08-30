#!/bin/sh
set -eu

config_dir=/boot/config/plugins/wise.route.manager
mkdir -p "$config_dir"
if [ ! -f "$config_dir/wise.route.manager.cfg" ]; then
  printf '%s\n' 'APP_URL=""' > "$config_dir/wise.route.manager.cfg"
  chmod 0600 "$config_dir/wise.route.manager.cfg"
fi
