#!/usr/bin/env bash
# Controlel Home Assistant manual-test installer.
# Copy this file together with controlel-ha-test.zip to:
#   /homeassistant/config/controlel-test/
#
# Usage:
#   bash /homeassistant/config/controlel-test/install-controlel-test.sh --up
#   bash /homeassistant/config/controlel-test/install-controlel-test.sh --rm
#   bash /homeassistant/config/controlel-test/install-controlel-test.sh --diag

set -eu

WORK_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
BUNDLE="${WORK_DIR}/controlel-ha-test.zip"
MODE=""

usage_error() {
  printf 'ERROR E_BUNDLE: use --up/-up, --rm/-rm, or --diag/-diag\n' >&2
  printf 'RESULT=ERROR\n' >&2
  exit 1
}

if [ "$#" -ne 1 ]; then
  usage_error
fi

case "$1" in
  --up|-up) MODE=up ;;
  --rm|-rm) MODE=rm ;;
  --diag|-diag) MODE=diag ;;
  *) usage_error ;;
esac

if [ ! -f "${BUNDLE}" ]; then
  printf 'ERROR E_BUNDLE: missing bundle: %s\n' "${BUNDLE}" >&2
  printf 'RESULT=ERROR\n' >&2
  exit 1
fi

# Fail closed on Docker/protection-mode before mutating anything.
# Diagnostics also require Docker to inspect the Core container.
if ! docker info >/dev/null 2>&1; then
  printf 'ERROR E_DOCKER: Docker unavailable. Disable Protection mode for Advanced SSH & Web Terminal and restart the app.\n' >&2
  printf 'RESULT=ERROR\n' >&2
  exit 1
fi

STAGE="${WORK_DIR}/.bootstrap-$$"
cleanup() {
  rm -rf "${STAGE}"
}
trap cleanup EXIT

mkdir -p "${STAGE}"
# Extract only the installer modules first; full staging happens in Python.
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  printf 'ERROR E_BUNDLE: python3 is required on the SSH host\n' >&2
  printf 'RESULT=ERROR\n' >&2
  exit 1
fi

"${PYTHON}" - "${BUNDLE}" "${STAGE}" <<'PY'
import sys
import zipfile
from pathlib import Path

bundle = Path(sys.argv[1])
stage = Path(sys.argv[2])
needed = (
    "installer/ha_test_installer.py",
    "installer/ha_test_bundle.py",
)
with zipfile.ZipFile(bundle, "r") as archive:
    names = set(archive.namelist())
    missing = [name for name in needed if name not in names]
    if missing:
        raise SystemExit(f"bundle missing installer modules: {missing}")
    for name in needed:
        target = stage / Path(name).name
        target.write_bytes(archive.read(name))
PY

"${PYTHON}" "${STAGE}/ha_test_installer.py" --mode "${MODE}" --work-dir "${WORK_DIR}"
