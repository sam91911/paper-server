#!/usr/bin/env bash
set -euo pipefail

if [[ $# -eq 0 && -n ${PAPER_DATABASE_URL:-} ]]; then
  if [[ -n ${PAPER_PDF_DIR:-} && $PAPER_PDF_DIR != /* ]]; then
    export PAPER_PDF_DIR=$PWD/$PAPER_PDF_DIR
  fi
  cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
  exec python3 -B -m paper_app.server
fi

if [[ $# -ne 1 || -z "$1" ]]; then
  printf 'Usage: %s PATH_TO_SQLITE_DATABASE or set PAPER_DATABASE_URL and PAPER_PDF_DIR\n' "$0" >&2
  exit 2
fi

database=$1
if [[ $database != /* ]]; then
  database=$PWD/$database
fi

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
exec python3 -B -m paper_app.server --database="$database"
