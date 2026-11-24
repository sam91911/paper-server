#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

case "${1:-}" in
  --postgres)
    [[ $# -eq 1 ]] || exit 2
    : "${PAPER_TEST_POSTGRES_URL:?Set PAPER_TEST_POSTGRES_URL to a test database}"
    python3 -m unittest discover -s tests -p test_postgres.py -v
    ;;
  "")
    [[ $# -eq 0 ]] || exit 2
    python3 -m compileall -q paper_app paper_client scripts
    python3 -m unittest discover -s tests -v
    node --test tests/*.mjs
    for source in paper_app/web/*.js vscode-extension/*.js; do
      node --check "$source"
    done
    for source in run_paper_server.sh scripts/*.sh scripts/*.bash; do
      bash -n "$source"
    done
    ;;
  *)
    printf 'Usage: bash scripts/check.sh [--postgres]\n' >&2
    exit 2
    ;;
esac
