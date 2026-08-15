#!/bin/sh
set -e

if [ "$1" = "process" ] || [ "$1" = "init-db" ] || [ "$1" = "serve" ]; then
  exec album-dvd-burner "$@"
fi

if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
  exec album-dvd-burner --help
fi

# Default: start web UI
exec album-dvd-burner serve --host 0.0.0.0 --port "${WEB_PORT:-8080}"
