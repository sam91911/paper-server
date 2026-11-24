#!/usr/bin/env bash
set -euo pipefail

project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
if (( $# > 1 )); then
  printf 'Usage: bash scripts/check-install.sh [output-directory]\n' >&2
  exit 2
fi
output_dir=
if (( $# == 1 )); then
  mkdir -p -- "$1"
  output_dir=$(cd -- "$1" && pwd)
fi
work_dir=$(mktemp -d)
trap 'rm -rf -- "$work_dir"' EXIT

python3 -m pip wheel --no-deps --wheel-dir "$work_dir/wheels" "$project_dir"
python3 -m venv "$work_dir/server"
"$work_dir/server/bin/python" -m pip install "$work_dir"/wheels/*.whl

cd -- "$work_dir"
"$work_dir/server/bin/python" -I "$project_dir/scripts/check_installed_workflow.py"
if [[ -n "$output_dir" ]]; then
  cp -- "$work_dir"/wheels/*.whl "$work_dir/paper-client.zip" "$output_dir/"
fi
