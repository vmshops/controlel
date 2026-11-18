#!/usr/bin/env bash
set -euo pipefail
set +x
CI_ROOT=$(git rev-parse --show-toplevel)
cd "$CI_ROOT"
[[ "${CI_COMMIT_SHA:-}" =~ ^[0-9a-f]{40}$ ]] || { echo 'Missing/invalid full CI_COMMIT_SHA'; exit 1; }
test "$(git rev-parse HEAD)" = "$CI_COMMIT_SHA"
python -c 'import sys; assert sys.platform == "linux"; assert sys.version_info[:2] == (3, 14) and sys.version_info >= (3, 14, 2), sys.version'
case "${CI_PIPELINE_EVENT:-}" in
  manual) TEST_PROFILE=${TEST_PROFILE:-FULL} ;;
  tag|release) TEST_PROFILE=${TEST_PROFILE:-RELEASE} ;;
  push|pull_request) TEST_PROFILE=${TEST_PROFILE:-FAST} ;;
  *) echo 'Unsupported pipeline event'; exit 1 ;;
esac
case "$TEST_PROFILE" in FAST|FULL|RELEASE) ;; *) echo 'Invalid TEST_PROFILE'; exit 1;; esac
export TEST_PROFILE
printf 'Controlel profile=%s commit=%s event=%s\n' "$TEST_PROFILE" "$CI_COMMIT_SHA" "$CI_PIPELINE_EVENT"
CI_PRIVATE=$(mktemp -d /tmp/controlel-ci-XXXXXXXX)
chmod 700 "$CI_PRIVATE"
trap 'rm -rf -- "$CI_PRIVATE"' EXIT
python -m venv "$CI_PRIVATE/environment"
export PATH="$CI_PRIVATE/environment/bin:$PATH"
unset PYTHONPATH PYTHONHOME
