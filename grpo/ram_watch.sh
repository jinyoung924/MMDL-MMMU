#!/usr/bin/env bash
# Stop only our unit $1 when MemAvailable < 5 GB (systemd-oomd otherwise kills whole scopes, incl. the user's jobs).
while systemctl --user is-active -q "$1"; do
  a=$(awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo)
  if [ "$a" -lt 5 ]; then systemctl --user stop "$1"; echo "$(date) MemAvailable ${a}GB -> stopped $1"; exit 0; fi
  sleep 15
done
echo "$(date) $1 finished"
