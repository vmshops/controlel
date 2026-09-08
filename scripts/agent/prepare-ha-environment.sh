#!/usr/bin/env bash
# Bind one pre-created WSL HA environment to one selected worktree/profile.
set -euo pipefail

usage() {
  echo "usage: $0 --worktree <wsl-path> --baseline <sha> --profile <checked-out-wheel|source-candidate> --environment <venv>" >&2
  exit 2
}

worktree="" baseline="" profile="" environment=""
while (($#)); do
  case "$1" in
    --worktree) worktree=${2:-}; shift 2 ;;
    --baseline) baseline=${2:-}; shift 2 ;;
    --profile) profile=${2:-}; shift 2 ;;
    --environment) environment=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$worktree" && -n "$baseline" && -n "$profile" && -n "$environment" ]] || usage
[[ "$profile" == "checked-out-wheel" || "$profile" == "source-candidate" ]] || usage
[[ -x "$environment/bin/python" ]] || { echo "HA environment is unavailable: $environment" >&2; exit 1; }
[[ -d "$worktree/.git" || -f "$worktree/.git" ]] || { echo "worktree is not a Git worktree: $worktree" >&2; exit 1; }

windows_worktree=$(wslpath -w "$worktree")
head=$(git.exe -C "$windows_worktree" rev-parse HEAD | tr -d '\r')
git.exe -C "$windows_worktree" merge-base --is-ancestor "$baseline" "$head"
lock_hash=$(sha256sum "$worktree/requirements/ha-test.txt" | awk '{print $1}')
fingerprint="$environment/.controlel-harness-v2.json"
if [[ -e "$fingerprint" ]]; then
  echo "refusing to overwrite existing fingerprint: $fingerprint" >&2
  exit 1
fi
if [[ "$profile" == "source-candidate" ]]; then
  installed=$("$environment/bin/python" -c 'import importlib.metadata; print(importlib.metadata.version("controlel"))' 2>/dev/null || true)
  [[ -z "$installed" ]] || { echo "source/candidate environment contains installed controlel ($installed)" >&2; exit 1; }
fi
umask 077
printf '{\n  "profile": "%s",\n  "baseline": "%s",\n  "ha_lock_sha256": "%s",\n  "worktree": "%s"\n}\n' "$profile" "$baseline" "$lock_hash" "$worktree" > "$fingerprint"
echo "Prepared fingerprint: $fingerprint"
