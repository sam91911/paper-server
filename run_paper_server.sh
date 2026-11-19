#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || -z "$1" ]]; then
  printf 'Usage: %s PATH_TO_SQLITE_DATABASE\n' "$0" >&2
  exit 2
fi

database=$1
if [[ $database != /* ]]; then
  database=$PWD/$database
fi

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
exec python3 -B -m paper_app.server --database="$database"
