#!/bin/sh
set -eu

iface=${1:-br0}

cidr=$(ip -o -4 addr show dev "$iface" 2>/dev/null | awk '{print $4}' | head -n 1 || true)
[ -n "$cidr" ] || cidr=$(ip -o -4 addr show scope global 2>/dev/null | awk '{print $4}' | head -n 1 || true)
[ -n "$cidr" ] || { printf '192.168.1.40\n'; exit 0; }

base=${cidr%/*}
prefix=$(printf '%s\n' "$base" | awk -F. '{print $1 "." $2 "." $3}')
host_last=$(printf '%s\n' "$base" | awk -F. '{print $4}')

for last in $(seq 40 99); do
  [ "$last" = "$host_last" ] && continue
  candidate="$prefix.$last"
  if ping -c 1 -W 1 "$candidate" >/dev/null 2>&1; then
    continue
  fi
  if ip neigh show "$candidate" 2>/dev/null | grep -qiE 'lladdr|REACHABLE|STALE|DELAY|PROBE'; then
    continue
  fi
  printf '%s\n' "$candidate"
  exit 0
done

printf '%s.40\n' "$prefix"
