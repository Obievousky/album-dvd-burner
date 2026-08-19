#!/usr/bin/env bash

set -euo pipefail

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$project_root/.env"

env_value() {
    local key="$1"
    local fallback="$2"
    local value="${!key:-}"

    if [[ -z "$value" && -f "$env_file" ]]; then
        value="$(sed -n "s/^${key}=//p" "$env_file" | tail -n 1)"
    fi

    printf '%s' "${value:-$fallback}"
}

data_root="$(env_value DATA_ROOT ./data)"
app_uid="$(env_value APP_UID 10001)"
app_gid="$(env_value APP_GID 10001)"

if [[ ! "$app_uid" =~ ^[0-9]+$ || ! "$app_gid" =~ ^[0-9]+$ ]]; then
    printf 'APP_UID and APP_GID must be numeric values.\n' >&2
    exit 1
fi

if [[ "$data_root" != /* ]]; then
    data_root="$project_root/$data_root"
fi

data_root="$(realpath -m "$data_root")"

if [[ "$EUID" -eq 0 ]]; then
    mkdir -p "$data_root"
    chown "$app_uid:$app_gid" "$data_root"
    chmod 0750 "$data_root"
else
    sudo mkdir -p "$data_root"
    sudo chown "$app_uid:$app_gid" "$data_root"
    sudo chmod 0750 "$data_root"
fi
actual_uid="$(stat -c '%u' "$data_root")"
actual_gid="$(stat -c '%g' "$data_root")"
actual_mode="$(stat -c '%a' "$data_root")"

if [[ "$actual_uid" != "$app_uid" || \
      "$actual_gid" != "$app_gid" || \
      "$actual_mode" != "750" ]]; then

    printf 'Failed to provision %s correctly.\n' "$data_root" >&2
    printf 'Expected: %s:%s mode %s\n' \
        "$app_uid" "$app_gid" "750" >&2
    printf 'Actual:   %s:%s mode %s\n' \
        "$actual_uid" "$actual_gid" "$actual_mode" >&2
    exit 1
fi

printf 'Provisioned %s for app user %s:%s (mode %s).\n' \
    "$data_root" "$app_uid" "$app_gid" "$actual_mode"