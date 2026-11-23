#!/usr/bin/env bash
set -euo pipefail

if [[ $# -eq 0 && -z ${PAPER_DATABASE_URL:-} ]] || [[ $# -gt 0 && -z $1 ]]; then
  printf 'Usage: %s [PATH_TO_SQLITE_DATABASE] [SERVER_OPTIONS]\n' "$0" >&2
  printf 'Set PAPER_DATABASE_URL and PAPER_PDF_DIR for PostgreSQL. Use --help for options.\n' >&2
  exit 2
fi

if [[ $# -gt 0 && $1 != -* ]]; then
  database=$1
  shift
  set -- "--database=$database" "$@"
fi

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
# Load the repository package while keeping relative arguments in the caller's directory.
PYTHONPATH="$repo_dir${PYTHONPATH:+:$PYTHONPATH}" exec python3 -B -P -m paper_app.server "$@"
