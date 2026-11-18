#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
python -m pip install -r requirements/package-test.txt
python scripts/packaging/build_core_release.py
python -m twine check dist/*
python scripts/packaging/validate_artifacts.py dist
python scripts/packaging/verify_clean_install.py dist
