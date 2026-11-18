#!/usr/bin/env bash
source "$(dirname "$0")/common.sh"
# Preserve the currently approved Actions release version; do not invent a tag.
python scripts/packaging/build_hacs_release.py --version 0.14.2
python scripts/packaging/validate_hacs_release.py dist/hacs/controlel.zip --version 0.14.2 --checksum dist/hacs/controlel.zip.sha256
sha256sum dist/hacs/controlel.zip
