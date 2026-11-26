#!/usr/bin/env bash
set -euo pipefail

unit=paper-library.service
active=/opt/paper-library
releases=/opt/paper-library-releases

usage() {
  cat <<'HELP'
Usage: paper-libraryctl COMMAND [ARGUMENTS]

  start | stop | restart | reload | status | enable | disable
  logs [JOURNALCTL_OPTIONS]      Show recent service logs (use -f to follow)
  releases                      List installed releases and the active target
  upgrade [--restart] SOURCE    Install a checkout and activate it
  upgrade-release [--restart] TAG
                               Verify and install a published release wheel
  rollback [--restart] RELEASE  Activate an existing release directory

Set PAPER_LIBRARY_EXTRAS=postgres,google to install optional dependencies.
Use upgrade, upgrade-release, or rollback with sudo. Without --restart, activation reloads
the worker and waits for it to become ready.
HELP
}

fail() {
  printf '%s\n' "$*" >&2
  exit 1
}

install_published_release() {
  local release=$1 tag=$2 extras=$3
  local wheel="local_paper_library-${tag#v}-py3-none-any.whl"
  local base="https://github.com/sam91911/paper-server/releases/download/$tag"
  local digest
  local -a curl_options=(--fail --silent --show-error --location
                         --proto '=https' --proto-redir '=https' --retry 2 --max-time 120)
  curl -q "${curl_options[@]}" --output "$release/SHA256SUMS.txt" "$base/SHA256SUMS.txt" &&
    curl -q "${curl_options[@]}" --output "$release/$wheel" "$base/$wheel" || return 1
  digest=$(awk -v wheel="$wheel" '$2 == wheel || $2 == "*" wheel { print $1 }' "$release/SHA256SUMS.txt")
  [[ "$digest" =~ ^[[:xdigit:]]{64}$ ]] || return 1
  printf '%s  %s\n' "$digest" "$release/$wheel" | sha256sum --check --status || return 1
  "$release/.venv/bin/python" -m pip install "$release/$wheel${extras:+[$extras]}" &&
    printf '%s\n' "$tag" > "$release/release-tag"
}

switch_release() {
  local target=$1 temp
  temp=$(mktemp -d -- "${active}.switch.XXXXXXXX") || return 1
  if ! ln -s -- "$target" "$temp/current" || ! mv -Tf -- "$temp/current" "$active"; then
    rm -f -- "$temp/current"
    rmdir -- "$temp"
    return 1
  fi
  rmdir -- "$temp"
}

wait_for_worker() {
  local cursor=$1 invocation=$2 deadline=$((SECONDS + 135)) messages
  local -a journal_options=(-u "$unit" --no-pager -o cat)
  if [[ -n "$cursor" ]]; then
    journal_options+=(--after-cursor="$cursor")
  fi
  while (( SECONDS < deadline )); do
    messages=$(journalctl "${journal_options[@]}" "_SYSTEMD_INVOCATION_ID=$invocation") || return 1
    if [[ "$messages" == *"failed to start"* || "$messages" == *"Could not launch the replacement HTTP worker"* ]]; then
      return 1
    fi
    if [[ "$messages" =~ HTTP\ worker\ [0-9]+\ ready\ on\ port ]] && systemctl is-active --quiet "$unit"; then
      return 0
    fi
    sleep 1
  done
  return 1
}

activate() {
  local target=$1 mode=$2 previous=$3 journal cursor invocation
  journal=$(journalctl -u "$unit" -n 1 --show-cursor --no-pager -o cat)
  cursor=$(sed -n 's/^-- cursor: //p' <<< "$journal" | tail -n 1)
  if [[ "$mode" == reload && -z "$cursor" ]]; then
    fail "Service journal has no cursor. Use --restart to start a new service invocation."
  fi
  switch_release "$target" || fail "Could not switch the release link to $target."
  if systemctl "$mode" "$unit" &&
      invocation=$(systemctl show "$unit" --property=InvocationID --value) &&
      [[ -n "$invocation" && "$invocation" != 00000000000000000000000000000000 ]] &&
      wait_for_worker "$cursor" "$invocation"; then
    printf 'Active release %s\n' "$target"
    return
  fi
  switch_release "$previous" || fail "Activation failed and the release link could not be restored. Check $active."
  if [[ "$mode" == restart ]]; then
    systemctl restart "$unit" || true
  fi
  journalctl -u "$unit" -n 25 --no-pager >&2 || true
  fail "Activation failed. Restored the release link to $previous. Check service status and logs."
}

command=${1:-help}
if (( $# )); then shift; fi
case "$command" in
  help|-h|--help) usage ;;
  status)
    [[ $# -eq 0 ]] || fail "Usage: paper-libraryctl status"
    if target=$(readlink -e -- "$active") && [[ -f "$target/release-tag" ]]; then
      printf 'Configured release %s (%s)\n' "$(cat -- "$target/release-tag")" "$target"
    fi
    exec systemctl status "$unit"
    ;;
  start|stop|restart|reload|enable|disable)
    [[ $# -eq 0 ]] || fail "Usage: paper-libraryctl $command"
    exec systemctl "$command" "$unit"
    ;;
  logs)
    exec journalctl -u "$unit" -n 50 --no-pager "$@"
    ;;
  releases)
    [[ $# -eq 0 ]] || fail "Usage: paper-libraryctl releases"
    printf 'Active release %s\n' "$(readlink -f -- "$active" || true)"
    if [[ -d "$releases" ]]; then
      find "$releases" -mindepth 1 -maxdepth 1 -type d -print | sort
    fi
    ;;
  upgrade|upgrade-release|rollback)
    mode=reload
    if [[ ${1:-} == --restart ]]; then mode=restart; shift; fi
    if [[ $# -ne 1 ]]; then usage >&2; exit 2; fi
    [[ $EUID -eq 0 ]] || fail "Run $command with sudo."
    [[ -L "$active" ]] || fail "$active must be a symlink to an installed release."
    if [[ "$command" == upgrade-release ]]; then
      target=$1
      [[ "$target" =~ ^v0\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]] || fail "Choose a release tag in the form v0.x.y."
    else
      target=$(realpath -e -- "$1") || fail "Directory does not exist."
      [[ -d "$target" ]] || fail "Choose a directory."
    fi
    install -d -m 0755 -- "$releases"
    releases=$(realpath -e -- "$releases")
    exec 9>"$releases/.activation.lock"
    flock -x 9
    previous=$(readlink -e -- "$active") || fail "The active release link is broken."
    [[ -x "$previous/.venv/bin/python" ]] || fail "The active release has no Python environment."
    if [[ "$mode" == reload ]]; then
      systemctl is-active --quiet "$unit" || fail "The service is stopped. Use --restart to activate and start it."
      [[ $(systemctl show "$unit" --property=CanReload --value) == yes ]] || fail "Install the reloadable service unit or use --restart."
    fi
    if [[ "$command" != rollback ]]; then
      if [[ "$command" == upgrade ]]; then
        [[ -f "$target/pyproject.toml" && -d "$target/paper_app" ]] || fail "Choose a Paper Library source checkout."
      fi
      extras=${PAPER_LIBRARY_EXTRAS:-}
      if [[ -n "$extras" && ! "$extras" =~ ^(postgres|google)(,(postgres|google))*$ ]]; then
        fail "PAPER_LIBRARY_EXTRAS accepts postgres and google, separated by a comma."
      fi
      release=$(mktemp -d -- "$releases/release.XXXXXXXX")
      chmod 0755 -- "$release"
      if python3 -m venv "$release/.venv" &&
          { if [[ "$command" == upgrade-release ]]; then
              install_published_release "$release" "$target" "$extras"
            else
              "$release/.venv/bin/python" -m pip install "${target}${extras:+[$extras]}"
            fi; } &&
          "$release/.venv/bin/python" -P -m paper_app.server --help >/dev/null; then
        target=$release
      else
        rm -rf -- "$release"
        fail "Release installation failed. The active release link is unchanged."
      fi
    else
      [[ $(dirname -- "$target") == "$releases" && -x "$target/.venv/bin/python" ]] ||
        fail "Choose an installed release directory under $releases."
    fi
    [[ "$target" != "$previous" ]] || fail "That release is already active."
    activate "$target" "$mode" "$previous"
    ;;
  *) usage >&2; exit 2 ;;
esac
