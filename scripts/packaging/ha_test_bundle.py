"""Shared Home Assistant manual-test bundle contract helpers."""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

BUNDLE_SCHEMA_VERSION = 2
INSTALLER_SCHEMA_VERSION = 2
BUNDLE_FILENAME = "controlel-ha-test.zip"
INSTALLER_FILENAME = "install-controlel-test.sh"
BUNDLE_JSON = "bundle.json"
CORE_DIR = "core"
INTEGRATION_ARCHIVE = "integration/controlel.zip"
INSTALLER_MODULE = "installer/ha_test_installer.py"
HA_TEST_BUILD_MARKER = "ha_test_build.json"
DOMAIN = "controlel"

# Exact Controlel-owned Home Assistant Store key prefixes. Files under
# ``config/.storage`` matching these prefixes (plus a config-entry id suffix)
# are exclusively owned by Controlel and may be removed after config-entry
# removal. Never widen this to unrelated storage.
CONTROLEL_STORAGE_KEY_PREFIXES = (
    "controlel.setup.",
    "controlel.water_safety.state.",
    "controlel.water_safety.evidence.",
)

# Home Assistant hassfest accepts CALVER/SEMVER/SIMPLEVER/BUILDVER/PEP440.
# Use an unambiguous PEP 440 development local version so consecutive dirty
# builds never share the public integration version string alone.
_HA_TEST_VERSION_RE = re.compile(r"^(?P<base>\d+\.\d+\.\d+)\.dev0\+ha\.test\.(?P<token>[a-z0-9]{8,32})$")


class HaTestBundleError(ValueError):
    """Raised when a HA test bundle contract is violated."""


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_ha_valid_test_version(version: str) -> bool:
    """Return True when version is the project HA-valid test identity format."""
    return _HA_TEST_VERSION_RE.fullmatch(version) is not None


def make_test_integration_version(source_version: str, content_token: str) -> str:
    """Derive an HA-valid development-only integration version."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", source_version):
        raise HaTestBundleError(f"unsupported source integration version: {source_version!r}")
    token = content_token.lower()
    if not re.fullmatch(r"[a-z0-9]{8,32}", token):
        raise HaTestBundleError(f"content token must be 8-32 lowercase alnum, got {content_token!r}")
    version = f"{source_version}.dev0+ha.test.{token}"
    if not is_ha_valid_test_version(version):
        raise HaTestBundleError(f"produced invalid HA test version: {version!r}")
    return version


def make_build_id(*, source_commit: str, dirty: bool, content_token: str) -> str:
    """Stable display/build identity independent of wall-clock time alone."""
    short = source_commit.strip()[:12] or "unknown"
    dirty_mark = "dirty" if dirty else "clean"
    return f"{short}-{dirty_mark}-{content_token}"


def rewrite_integration_version_literal(source: str, *, new_version: str) -> str:
    """Rewrite the literal INTEGRATION_VERSION assignment in const.py text."""
    pattern = re.compile(
        r'^(INTEGRATION_VERSION\s*=\s*)(["\'])([^"\']*)\2',
        re.MULTILINE,
    )
    replaced, count = pattern.subn(rf'\1"{new_version}"', source, count=1)
    if count != 1:
        raise HaTestBundleError("const.py must declare exactly one INTEGRATION_VERSION literal")
    return replaced


def controlel_storage_filenames_for_entry(entry_id: str) -> tuple[str, ...]:
    """Return exact ``.storage`` filenames owned by one Controlel entry."""
    if not entry_id or any(ch in entry_id for ch in "/\\"):
        raise HaTestBundleError(f"unsafe config entry id: {entry_id!r}")
    return tuple(f"{prefix}{entry_id}" for prefix in CONTROLEL_STORAGE_KEY_PREFIXES)


def is_allowlisted_controlel_storage_name(name: str) -> bool:
    """Return True for exact Controlel-owned storage filenames only."""
    path = PurePosixPath(name)
    if path.name != name or "/" in name or "\\" in name or name in {".", ".."}:
        return False
    return any(name.startswith(prefix) and len(name) > len(prefix) for prefix in CONTROLEL_STORAGE_KEY_PREFIXES)


def validate_bundle_json(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate bundle.json provenance and return a normalized dict."""
    required = {
        "schema_version",
        "source_commit",
        "dirty",
        "build_id",
        "core_version",
        "integration_source_version",
        "integration_test_version",
        "core_wheel",
        "core_wheel_sha256",
        "integration_zip_sha256",
        "installer_schema_version",
        "installer_sha256",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise HaTestBundleError(f"bundle.json missing keys: {missing}")
    if payload.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise HaTestBundleError(f"unsupported bundle schema_version: {payload.get('schema_version')!r}")
    if payload.get("installer_schema_version") != INSTALLER_SCHEMA_VERSION:
        raise HaTestBundleError(f"unsupported installer_schema_version: {payload.get('installer_schema_version')!r}")
    if not isinstance(payload.get("dirty"), bool):
        raise HaTestBundleError("bundle.json dirty must be a boolean")
    for key in (
        "source_commit",
        "build_id",
        "core_version",
        "integration_source_version",
        "integration_test_version",
        "core_wheel",
        "core_wheel_sha256",
        "integration_zip_sha256",
        "installer_sha256",
    ):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise HaTestBundleError(f"bundle.json {key} must be a non-empty string")
    if not is_ha_valid_test_version(str(payload["integration_test_version"])):
        raise HaTestBundleError(f"integration_test_version is not HA-valid: {payload['integration_test_version']!r}")
    for key in ("core_wheel_sha256", "integration_zip_sha256", "installer_sha256"):
        digest = str(payload[key])
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise HaTestBundleError(f"bundle.json {key} must be a lowercase SHA-256 hex digest")
    wheel_name = str(payload["core_wheel"])
    if "/" in wheel_name or "\\" in wheel_name or not wheel_name.endswith(".whl"):
        raise HaTestBundleError(f"bundle.json core_wheel is unsafe: {wheel_name!r}")
    return dict(payload)


def validate_ha_test_bundle(archive: Path) -> dict[str, Any]:
    """Validate a controlel-ha-test.zip before any installation mutation."""
    if archive.name != BUNDLE_FILENAME:
        raise HaTestBundleError(f"bundle must be named {BUNDLE_FILENAME}, found {archive.name}")
    try:
        with zipfile.ZipFile(archive, "r") as bundle:
            names = bundle.namelist()
            if len(names) != len(set(names)):
                raise HaTestBundleError("bundle contains duplicate paths")
            if BUNDLE_JSON not in names or INTEGRATION_ARCHIVE not in names:
                raise HaTestBundleError("bundle is missing bundle.json or integration ZIP")
            core_names = [name for name in names if name.startswith(f"{CORE_DIR}/") and name.endswith(".whl")]
            if len(core_names) != 1:
                raise HaTestBundleError("bundle must contain exactly one Core wheel")
            raw = json.loads(bundle.read(BUNDLE_JSON).decode("utf-8"))
            if not isinstance(raw, dict):
                raise HaTestBundleError("bundle.json must be a JSON object")
            metadata = validate_bundle_json(raw)
            wheel_path = f"{CORE_DIR}/{metadata['core_wheel']}"
            if core_names[0] != wheel_path:
                raise HaTestBundleError("bundle.json core_wheel does not match archive contents")
            wheel_content = bundle.read(wheel_path)
            integration_content = bundle.read(INTEGRATION_ARCHIVE)
            if sha256_bytes(wheel_content) != metadata["core_wheel_sha256"]:
                raise HaTestBundleError("Core wheel SHA-256 mismatch")
            if sha256_bytes(integration_content) != metadata["integration_zip_sha256"]:
                raise HaTestBundleError("integration ZIP SHA-256 mismatch")
            _validate_embedded_integration(integration_content, metadata)
            return metadata
    except HaTestBundleError:
        raise
    except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HaTestBundleError(f"cannot read HA test bundle {archive}") from error


def _validate_embedded_integration(content: bytes, metadata: Mapping[str, Any]) -> None:
    with zipfile.ZipFile(io.BytesIO(content), "r") as archive:
        names = set(archive.namelist())
        if "manifest.json" not in names or "const.py" not in names:
            raise HaTestBundleError("integration ZIP is missing manifest.json or const.py")
        if HA_TEST_BUILD_MARKER not in names:
            raise HaTestBundleError("integration ZIP is missing ha_test_build.json marker")
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        if manifest.get("version") != metadata["integration_test_version"]:
            raise HaTestBundleError("integration manifest version does not match bundle.json")
        marker = json.loads(archive.read(HA_TEST_BUILD_MARKER).decode("utf-8"))
        if marker.get("build_id") != metadata["build_id"]:
            raise HaTestBundleError("ha_test_build.json build_id does not match bundle.json")
        const_text = archive.read("const.py").decode("utf-8")
        if f'INTEGRATION_VERSION = "{metadata["integration_test_version"]}"' not in const_text:
            raise HaTestBundleError("const.py INTEGRATION_VERSION does not match test identity")
