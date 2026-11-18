#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
python -m pip install -e .
python -m pip install pytest ruff -r requirements/package-test.txt
python -m ruff check .
python -m ruff format --check .
python -B scripts/ci/test_harness.py -v
python -m pytest tests/domain tests/application tests/frontend_api tests/infrastructure tests/architecture tests/packaging
