#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
case "${1:-}" in checked-out-wheel|public) composition=$1 ;; *) echo 'Explicit HA composition required'; exit 1 ;; esac
python -m pip install --require-hashes -r requirements/ha-test.txt
if [[ "$composition" == checked-out-wheel ]]; then
  python -m pip install -r requirements/package-test.txt
else
  python scripts/ci/public_core_artifact.py --install
fi
bash scripts/agent/prepare-ha-environment.sh --worktree "$CI_ROOT" --baseline "$CI_COMMIT_SHA" --profile "$composition" --environment "$CI_PRIVATE/environment"
bash scripts/agent/ha-test.sh --worktree "$CI_ROOT" --baseline "$CI_COMMIT_SHA" --profile "$composition" --environment "$CI_PRIVATE/environment" -- tests/integrations/home_assistant --asyncio-mode=auto --ignore=tests/integrations/home_assistant/framework
bash scripts/agent/ha-test.sh --worktree "$CI_ROOT" --baseline "$CI_COMMIT_SHA" --profile "$composition" --environment "$CI_PRIVATE/environment" -- tests/integrations/home_assistant/framework
