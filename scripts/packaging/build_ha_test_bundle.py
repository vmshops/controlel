"""Build the canonical Controlel Home Assistant manual-test bundle.

Canonical command (no required arguments):

    python scripts/packaging/build_ha_test_bundle.py

Always builds both the current-tree Core wheel and the current-tree Home
Assistant integration into fixed external filenames under ``dist/ha-test/``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

if __package__:
    from .build_core_release import build_core_release
    from .build_hacs_release import _archive_bytes
    from .ha_test_bundle import (
        BUNDLE_FILENAME,
        BUNDLE_JSON,
        BUNDLE_SCHEMA_VERSION,
        CORE_DIR,
        HA_TEST_BUILD_MARKER,
        INSTALLER_FILENAME,
        INSTALLER_MODULE,
        INSTALLER_SCHEMA_VERSION,
        INTEGRATION_ARCHIVE,
        HaTestBundleError,
        make_build_id,
        make_test_integration_version,
        rewrite_integration_version_literal,
        sha256_bytes,
        validate_ha_test_bundle,
    )
    from .integration_runtime_files import discover_repository_integration_runtime_files
else:
    from build_core_release import build_core_release
    from build_hacs_release import _archive_bytes
    from ha_test_bundle import (
        BUNDLE_FILENAME,
        BUNDLE_JSON,
        BUNDLE_SCHEMA_VERSION,
        CORE_DIR,
        HA_TEST_BUILD_MARKER,
        INSTALLER_FILENAME,
        INSTALLER_MODULE,
        INSTALLER_SCHEMA_VERSION,
        INTEGRATION_ARCHIVE,
        HaTestBundleError,
        make_build_id,
        make_test_integration_version,
        rewrite_integration_version_literal,
        sha256_bytes,
        validate_ha_test_bundle,
    )
    from integration_runtime_files import discover_repository_integration_runtime_files

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "dist" / "ha-test"
INSTALLER_SOURCE = Path(__file__).resolve().parent / "install_controlel_test.sh"
INSTALLER_LIB_SOURCE = Path(__file__).resolve().parent / "ha_test_installer.py"
BUNDLE_LIB_SOURCE = Path(__file__).resolve().parent / "ha_test_bundle.py"
BUNDLE_LIB_MODULE = "installer/ha_test_bundle.py"


def _project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle)["project"]["version"]
    if not isinstance(version, str) or not version:
        raise HaTestBundleError("project version must be a non-empty string")
    return version


def _integration_source_version(root: Path) -> str:
    source = (root / "custom_components" / "controlel" / "const.py").read_text(encoding="utf-8")
    match = re.search(r'^INTEGRATION_VERSION\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    if match is None:
        raise HaTestBundleError("integration source has no literal INTEGRATION_VERSION")
    return match.group(1)


def _git_identity(root: Path) -> tuple[str, bool]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = (
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            != ""
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        raise HaTestBundleError("git identity is required to build the HA test bundle") from error
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise HaTestBundleError(f"unexpected git commit identity: {commit!r}")
    return commit, dirty


def _build_test_integration(
    *,
    root: Path,
    source_version: str,
    core_version: str,
    source_commit: str,
    dirty: bool,
) -> tuple[bytes, dict[str, object]]:
    files = discover_repository_integration_runtime_files(root)
    if "manifest.json" not in files or "const.py" not in files:
        raise HaTestBundleError("integration runtime discovery is missing required files")

    # Content token covers runtime sources before test-only rewrites so the
    # identity stays stable for identical working-tree inputs.
    content_token = sha256_bytes(b"\0".join(files[name] for name in sorted(files)))[:12]
    test_version = make_test_integration_version(source_version, content_token)
    build_id = make_build_id(source_commit=source_commit, dirty=dirty, content_token=content_token)

    manifest = json.loads(files["manifest.json"].decode("utf-8"))
    if not isinstance(manifest, dict):
        raise HaTestBundleError("manifest.json must be a JSON object")
    public_requirements = manifest.get("requirements")
    if not isinstance(public_requirements, list) or len(public_requirements) != 1:
        raise HaTestBundleError("release manifest must contain one Core requirement")
    manifest["version"] = test_version
    manifest["requirements"] = [f"controlel=={core_version}"]

    marker = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "build_id": build_id,
        "source_commit": source_commit,
        "dirty": dirty,
        "integration_source_version": source_version,
        "integration_test_version": test_version,
        "core_version": core_version,
    }
    development_files = {
        **files,
        "manifest.json": (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        "const.py": rewrite_integration_version_literal(
            files["const.py"].decode("utf-8"),
            new_version=test_version,
        ).encode("utf-8"),
        HA_TEST_BUILD_MARKER: (json.dumps(marker, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }
    return _archive_bytes(development_files), {
        "content_token": content_token,
        "test_version": test_version,
        "build_id": build_id,
        "release_source_requirement": str(public_requirements[0]),
        "marker": marker,
    }


def build_ha_test_bundle(
    *,
    root: Path = ROOT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    core_wheel: Path | None = None,
) -> dict[str, object]:
    """Build ``controlel-ha-test.zip`` and ``install-controlel-test.sh``."""

    if not INSTALLER_SOURCE.is_file() or not INSTALLER_LIB_SOURCE.is_file() or not BUNDLE_LIB_SOURCE.is_file():
        raise HaTestBundleError("installer sources are missing from scripts/packaging")

    core_version = _project_version(root)
    source_version = _integration_source_version(root)
    source_commit, dirty = _git_identity(root)

    if core_wheel is None:
        if root.resolve() != ROOT.resolve():
            raise HaTestBundleError("a non-default source root requires an explicit Core wheel")
        core_wheel, _sdist = build_core_release()
    wheel_content = core_wheel.read_bytes()
    if not core_wheel.name.endswith(".whl"):
        raise HaTestBundleError(f"Core wheel name is invalid: {core_wheel.name}")

    integration_content, identity = _build_test_integration(
        root=root,
        source_version=source_version,
        core_version=core_version,
        source_commit=source_commit,
        dirty=dirty,
    )

    bundle_metadata = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "source_commit": source_commit,
        "dirty": dirty,
        "build_id": identity["build_id"],
        "core_version": core_version,
        "integration_source_version": source_version,
        "integration_test_version": identity["test_version"],
        "core_wheel": core_wheel.name,
        "core_wheel_sha256": sha256_bytes(wheel_content),
        "integration_zip_sha256": sha256_bytes(integration_content),
        "installer_schema_version": INSTALLER_SCHEMA_VERSION,
        "installer_sha256": sha256_bytes(
            b"\0".join(
                [
                    INSTALLER_SOURCE.read_bytes(),
                    INSTALLER_LIB_SOURCE.read_bytes(),
                    BUNDLE_LIB_SOURCE.read_bytes(),
                ]
            )
        ),
        "built_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "release_source_requirement": identity["release_source_requirement"],
        "development_requirement": f"controlel=={core_version}",
        "publishable": False,
    }

    outer_files = {
        BUNDLE_JSON: (json.dumps(bundle_metadata, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        f"{CORE_DIR}/{core_wheel.name}": wheel_content,
        INTEGRATION_ARCHIVE: integration_content,
        INSTALLER_MODULE: INSTALLER_LIB_SOURCE.read_bytes(),
        BUNDLE_LIB_MODULE: BUNDLE_LIB_SOURCE.read_bytes(),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / BUNDLE_FILENAME
    installer_path = output_dir / INSTALLER_FILENAME
    bundle_path.write_bytes(_archive_bytes(outer_files))
    installer_text = INSTALLER_SOURCE.read_text(encoding="utf-8")
    if not installer_text.endswith("\n"):
        installer_text += "\n"
    installer_path.write_text(installer_text, encoding="utf-8", newline="\n")
    try:
        installer_path.chmod(installer_path.stat().st_mode | 0o755)
    except OSError:
        pass

    validate_ha_test_bundle(bundle_path)
    return bundle_metadata


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for the two fixed external artifacts (default: dist/ha-test)",
    )
    parser.add_argument(
        "--core-wheel",
        type=Path,
        help="Optional prebuilt Core wheel (tests / non-default roots)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    metadata = build_ha_test_bundle(
        output_dir=arguments.output_dir,
        core_wheel=arguments.core_wheel,
    )
    print(f"Built {arguments.output_dir / BUNDLE_FILENAME}")
    print(f"Built {arguments.output_dir / INSTALLER_FILENAME}")
    print(f"BUILD={metadata['build_id']}")
    print(f"INSTALLER={metadata['installer_sha256'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
