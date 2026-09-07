#!/usr/bin/env bash
# Run Home Assistant tests only from an explicitly selected WSL worktree and environment.
set -euo pipefail

usage() {
  echo "usage: $0 --worktree <wsl-path> --baseline <sha> --profile <checked-out-wheel|source-candidate> --environment <venv> [--validate] [-- <pytest arguments>]" >&2
  exit 2
}

worktree="" baseline="" profile="" environment="" validate_only=false
while (($#)); do
  case "$1" in
    --worktree) worktree=${2:-}; shift 2 ;;
    --baseline) baseline=${2:-}; shift 2 ;;
    --profile) profile=${2:-}; shift 2 ;;
    --environment) environment=${2:-}; shift 2 ;;
    --validate) validate_only=true; shift ;;
    --) shift; break ;;
    *) usage ;;
  esac
done
[[ -n "$worktree" && -n "$baseline" && -n "$profile" && -n "$environment" ]] || usage
[[ -d "$worktree/.git" || -f "$worktree/.git" ]] || { echo "worktree is not a Git worktree: $worktree" >&2; exit 1; }
[[ -x "$environment/bin/python" ]] || { echo "HA environment is unavailable: $environment" >&2; exit 1; }
[[ "$profile" == "checked-out-wheel" || "$profile" == "source-candidate" ]] || usage

windows_worktree=$(wslpath -w "$worktree")
head=$(git.exe -C "$windows_worktree" rev-parse HEAD | tr -d '\r')
git.exe -C "$windows_worktree" merge-base --is-ancestor "$baseline" "$head"
lock_hash=$(sha256sum "$worktree/requirements/ha-test.txt" | awk '{print $1}')
fingerprint="$environment/.controlel-harness-v2.json"
[[ -f "$fingerprint" ]] || { echo "missing HA environment fingerprint: $fingerprint" >&2; exit 1; }
python="$environment/bin/python"

CONTROLEL_HARNESS_BASELINE="$baseline" "$python" - "$fingerprint" "$profile" "$head" "$lock_hash" "$worktree" <<'PY'
import json, os, sys
from pathlib import Path
path, profile, head, lock_hash, worktree = map(str, sys.argv[1:])
data = json.loads(Path(path).read_text())
expected = {"profile": profile, "baseline": os.environ["CONTROLEL_HARNESS_BASELINE"], "ha_lock_sha256": lock_hash, "worktree": worktree}
for key, value in expected.items():
    if data.get(key) != value:
        raise SystemExit(f"environment fingerprint mismatch for {key}: {data.get(key)!r} != {value!r}")
PY

if "$validate_only"; then
  exit 0
fi

cd "$worktree"
if [[ "$profile" == "checked-out-wheel" ]]; then
  wheel_dir=$(mktemp -d)
  trap 'rm -rf "$wheel_dir"' EXIT
  "$python" -m build --wheel --outdir "$wheel_dir"
  wheel=$(find "$wheel_dir" -maxdepth 1 -name 'controlel-*.whl' -print -quit)
  [[ -n "$wheel" ]] || { echo "Core wheel was not built" >&2; exit 1; }
  "$python" -m pip install --force-reinstall --no-deps "$wheel"
  "$python" scripts/ci/verify_public_core.py --development-wheel "$wheel"
  CONTROLEL_FRAMEWORK_COMPOSITION=checked-out-wheel "$python" -m pytest "$@"
else
  # Source/candidate is deliberately bound to this one worktree; no installed Core is accepted.
  installed=$("$python" -c 'import importlib.metadata; print(importlib.metadata.version("controlel"))' 2>/dev/null || true)
  [[ -z "$installed" ]] || { echo "source/candidate environment must not contain installed controlel ($installed)" >&2; exit 1; }
  PYTHONPATH="$worktree/src${PYTHONPATH:+:$PYTHONPATH}" "$python" -m pytest --asyncio-mode=auto "$@"
fi
