#!/bin/sh
set -e

warn_data_root() {
  data_dir="${DATA_ROOT:-/data}"
  if [ ! -d "$data_dir" ]; then
    echo "WARNING: DATA_ROOT '$data_dir' does not exist." >&2
    echo "         Create and own it with: ./docker/provision.sh" >&2
  elif [ ! -w "$data_dir" ]; then
    echo "WARNING: DATA_ROOT '$data_dir' is not writable by uid $(id -u) (gid $(id -g))." >&2
    echo "         Fix ownership with: ./docker/provision.sh" >&2
  fi
}

if [ "$1" = "process" ]; then
  warn_data_root
  exec album-dvd-burner "$@"
fi

if [ "$1" = "init-db" ]; then
  exec album-dvd-burner "$@"
fi

if [ "$1" = "serve" ]; then
  warn_data_root
  exec album-dvd-burner "$@"
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
  exec album-dvd-burner --help
fi

# Default: start web UI
warn_data_root
exec album-dvd-burner serve --host 0.0.0.0 --port "${WEB_PORT:-8080}"
