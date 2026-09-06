"""Home Assistant manual-test installer library.

Invoked by ``install-controlel-test.sh``. External Docker / Supervisor / HA
operations are injectable so unit tests never need a live Home Assistant.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

# Support both package imports and the extracted installer/ directory on HA OS.
if not __package__:
    _installer_dir = Path(__file__).resolve().parent
    if str(_installer_dir) not in sys.path:
        sys.path.insert(0, str(_installer_dir))

if __package__:
    from .ha_test_bundle import (
        BUNDLE_FILENAME,
        CORE_DIR,
        DOMAIN,
        HA_TEST_BUILD_MARKER,
        INTEGRATION_ARCHIVE,
        HaTestBundleError,
        is_allowlisted_controlel_storage_name,
        validate_ha_test_bundle,
    )
else:
    from ha_test_bundle import (  # type: ignore[no-redef]
        BUNDLE_FILENAME,
        CORE_DIR,
        DOMAIN,
        HA_TEST_BUILD_MARKER,
        INTEGRATION_ARCHIVE,
        HaTestBundleError,
        is_allowlisted_controlel_storage_name,
        validate_ha_test_bundle,
    )


ERROR_DOCKER = "E_DOCKER"
ERROR_BUNDLE = "E_BUNDLE"
ERROR_HA_CONTAINER = "E_HA_CONTAINER"
ERROR_CORE_INSTALL = "E_CORE_INSTALL"
ERROR_INTEGRATION = "E_INTEGRATION"
ERROR_CONFIG_RESET = "E_CONFIG_RESET"
ERROR_HA_RESTART = "E_HA_RESTART"
ERROR_HA_READY = "E_HA_READY"
ERROR_VERIFY = "E_VERIFY"
ERROR_DIAG = "E_DIAG"

HA_READY_TIMEOUT_SECONDS = 300.0
HA_READY_POLL_SECONDS = 2.0

DIAGNOSTICS_FILENAME = "controlel-diagnostics.txt"
DIAG_LOG_TAIL_LINES = 200
DIAG_MAX_SECTION_CHARS = 80_000
DIAG_MAX_FILE_CHARS = 400_000

# Authoritative Home Assistant Core container paths. Never assume the Advanced
# SSH add-on's /homeassistant/config namespace is the same filesystem.
CONTAINER_STAGE_DIR = "/config/controlel-test/.stage"
CONTAINER_INTEGRATION_ZIP = f"{CONTAINER_STAGE_DIR}/controlel.zip"
CONTAINER_BUNDLE_JSON = f"{CONTAINER_STAGE_DIR}/bundle.json"
CONTAINER_CUSTOM_COMPONENTS = "/config/custom_components"
CONTAINER_LIVE_INTEGRATION = f"{CONTAINER_CUSTOM_COMPONENTS}/{DOMAIN}"
CONTAINER_STORAGE_DIR = "/config/.storage"

CommandRunner = Callable[[Sequence[str], Path | None], tuple[int, str, str]]
HttpExchange = Callable[[str, str, Mapping[str, str] | None, bytes | None], tuple[int, bytes]]


class InstallerError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class InstallerPaths:
    work_dir: Path
    bundle_path: Path
    config_root: Path
    log_path: Path


@dataclass
class InstallerServices:
    run_command: CommandRunner
    http_exchange: HttpExchange
    sleep: Callable[[float], None]
    time_monotonic: Callable[[], float]
    env: Mapping[str, str]


def default_run_command(argv: Sequence[str], cwd: Path | None = None) -> tuple[int, str, str]:
    import subprocess

    completed = subprocess.run(
        list(argv),
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def default_http_exchange(
    method: str,
    url: str,
    headers: Mapping[str, str] | None = None,
    body: bytes | None = None,
) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method.upper())
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return int(response.status), response.read()
    except urllib.error.HTTPError as error:
        return int(error.code), error.read()
    except urllib.error.URLError as error:
        raise InstallerError(ERROR_CONFIG_RESET, f"HA API unreachable: {error.reason}") from error


def default_services(env: Mapping[str, str] | None = None) -> InstallerServices:
    return InstallerServices(
        run_command=default_run_command,
        http_exchange=default_http_exchange,
        sleep=time.sleep,
        time_monotonic=time.monotonic,
        env=env if env is not None else os.environ,
    )


def _append_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"[{stamp}] {message}\n")


def _logged_command(
    services: InstallerServices,
    log_path: Path,
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
) -> tuple[int, str, str]:
    _append_log(log_path, f"$ {' '.join(argv)}")
    code, stdout, stderr = services.run_command(argv, cwd)
    if stdout:
        _append_log(log_path, f"stdout:\n{stdout.rstrip()}")
    if stderr:
        _append_log(log_path, f"stderr:\n{stderr.rstrip()}")
    _append_log(log_path, f"exit={code}")
    return code, stdout, stderr


def detect_docker(services: InstallerServices, log_path: Path) -> None:
    code, _stdout, stderr = _logged_command(services, log_path, ["docker", "info"])
    if code != 0:
        raise InstallerError(
            ERROR_DOCKER,
            "Docker unavailable. Disable Protection mode for Advanced SSH & Web Terminal and restart the app.",
        )
    if "permission denied" in stderr.casefold():
        raise InstallerError(
            ERROR_DOCKER,
            "Docker unavailable. Disable Protection mode for Advanced SSH & Web Terminal and restart the app.",
        )


def resolve_ha_container(services: InstallerServices, log_path: Path) -> str:
    configured = services.env.get("CONTROLEL_HA_CONTAINER", "").strip()
    if configured:
        code, _, _ = _logged_command(
            services,
            log_path,
            ["docker", "inspect", "--format", "{{.State.Running}}", configured],
        )
        if code != 0:
            raise InstallerError(ERROR_HA_CONTAINER, f"HA container missing: {configured}")
        return configured

    code, stdout, _ = _logged_command(
        services,
        log_path,
        [
            "docker",
            "ps",
            "--format",
            "{{.Names}}",
            "--filter",
            "name=homeassistant",
        ],
    )
    if code != 0:
        raise InstallerError(ERROR_HA_CONTAINER, "Unable to list HA containers")
    names = [line.strip() for line in stdout.splitlines() if line.strip()]
    preferred = [name for name in names if name == "homeassistant"] or names
    if not preferred:
        raise InstallerError(ERROR_HA_CONTAINER, "HA container missing")
    return preferred[0]


def _supervisor_headers(services: InstallerServices) -> dict[str, str]:
    token = services.env.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        token = services.env.get("CONTROLEL_HA_TOKEN", "").strip()
    if not token:
        raise InstallerError(
            ERROR_CONFIG_RESET,
            "No SUPERVISOR_TOKEN/CONTROLEL_HA_TOKEN available for config-entry API",
        )
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def _api_base(services: InstallerServices) -> str:
    return services.env.get("CONTROLEL_HA_API_BASE", "http://supervisor/core/api").rstrip("/")


def list_controlel_config_entries(services: InstallerServices, log_path: Path) -> list[dict[str, Any]]:
    headers = _supervisor_headers(services)
    url = f"{_api_base(services)}/config/config_entries/entry"
    _append_log(log_path, f"GET {url}")
    status, body = services.http_exchange("GET", url, headers, None)
    _append_log(log_path, f"status={status} body={body[:2000]!r}")
    if status != 200:
        raise InstallerError(ERROR_CONFIG_RESET, f"config entry list failed (HTTP {status})")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InstallerError(ERROR_CONFIG_RESET, "config entry list returned invalid JSON") from error
    if not isinstance(payload, list):
        raise InstallerError(ERROR_CONFIG_RESET, "config entry list must be a JSON array")
    entries = [item for item in payload if isinstance(item, dict) and item.get("domain") == DOMAIN]
    return entries


def remove_config_entry(services: InstallerServices, log_path: Path, entry_id: str) -> None:
    headers = _supervisor_headers(services)
    url = f"{_api_base(services)}/config/config_entries/entry/{entry_id}"
    _append_log(log_path, f"DELETE {url}")
    status, body = services.http_exchange("DELETE", url, headers, None)
    _append_log(log_path, f"status={status} body={body[:2000]!r}")
    if status not in {200, 204}:
        raise InstallerError(ERROR_CONFIG_RESET, f"config entry removal failed for {entry_id} (HTTP {status})")


def wait_for_ha(
    services: InstallerServices,
    log_path: Path,
    container: str,
    *,
    timeout_seconds: float = HA_READY_TIMEOUT_SECONDS,
) -> None:
    """Wait until HA Core is API-ready with config-entry/config-flow infrastructure.

    Docker ``State.Running`` alone is not sufficient: integrations and config-flow
    handlers may still be loading.
    """
    deadline = services.time_monotonic() + timeout_seconds
    headers = _supervisor_headers(services)
    api = _api_base(services)
    while services.time_monotonic() < deadline:
        code, stdout, _ = _logged_command(
            services,
            log_path,
            ["docker", "inspect", "--format", "{{.State.Running}}", container],
        )
        if code == 0 and stdout.strip().casefold() == "true":
            try:
                config_status, _ = services.http_exchange("GET", f"{api}/config", headers, None)
                entries_status, _ = services.http_exchange("GET", f"{api}/config/config_entries/entry", headers, None)
                handlers_status, handlers_body = services.http_exchange(
                    "GET", f"{api}/config/config_entries/flow_handlers", headers, None
                )
            except InstallerError as error:
                _append_log(log_path, f"HA readiness probe failed: {error.message}")
            else:
                if (
                    config_status == 200
                    and entries_status == 200
                    and handlers_status == 200
                    and _flow_handlers_include_controlel(handlers_body)
                ):
                    _append_log(log_path, "HA readiness confirmed (API + config-flow handlers)")
                    return
        services.sleep(HA_READY_POLL_SECONDS)
    raise InstallerError(
        ERROR_HA_READY,
        "Home Assistant did not become ready after restart",
    )


def _flow_handlers_include_controlel(body: bytes) -> bool:
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    if isinstance(payload, list):
        return DOMAIN in payload
    if isinstance(payload, dict):
        handlers = payload.get("handlers") or payload.get("flow_handlers")
        if isinstance(handlers, list):
            return DOMAIN in handlers
    return False


def smoke_controlel_config_flow(services: InstallerServices, log_path: Path) -> None:
    """Prove the Controlel config-flow handler loads, without leaving config behind."""
    headers = _supervisor_headers(services)
    api = _api_base(services)
    before = list_controlel_config_entries(services, log_path)
    before_ids = {entry.get("entry_id") for entry in before if isinstance(entry.get("entry_id"), str)}

    url = f"{api}/config/config_entries/flow"
    body = json.dumps({"handler": DOMAIN}).encode("utf-8")
    _append_log(log_path, f"POST {url} handler={DOMAIN}")
    status, response = services.http_exchange("POST", url, headers, body)
    _append_log(log_path, f"status={status} body={response[:2000]!r}")
    if status == 400 and b"Invalid handler" in response:
        raise InstallerError(
            ERROR_HA_READY,
            "Controlel config-flow handler unavailable after restart",
        )
    if status != 200:
        raise InstallerError(
            ERROR_HA_READY,
            f"Controlel config-flow smoke failed (HTTP {status})",
        )
    try:
        payload = json.loads(response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InstallerError(ERROR_HA_READY, "config-flow smoke returned invalid JSON") from error
    if not isinstance(payload, dict):
        raise InstallerError(ERROR_HA_READY, "config-flow smoke returned unexpected payload")
    if payload.get("handler") != DOMAIN:
        raise InstallerError(
            ERROR_HA_READY,
            "Controlel config-flow handler unavailable after restart",
        )
    result_type = payload.get("type")
    flow_id = payload.get("flow_id")
    if result_type not in {"form", "abort", "create_entry", "menu", "progress", "external"}:
        raise InstallerError(ERROR_HA_READY, "Controlel config-flow smoke returned unexpected type")

    if isinstance(flow_id, str) and flow_id and result_type in {"form", "menu", "progress", "external"}:
        delete_url = f"{api}/config/config_entries/flow/{flow_id}"
        _append_log(log_path, f"DELETE {delete_url}")
        delete_status, delete_body = services.http_exchange("DELETE", delete_url, headers, None)
        _append_log(log_path, f"status={delete_status} body={delete_body[:500]!r}")
        if delete_status not in {200, 204}:
            raise InstallerError(
                ERROR_HA_READY,
                "failed to abort temporary Controlel config flow after smoke",
            )

    after = list_controlel_config_entries(services, log_path)
    after_ids = {entry.get("entry_id") for entry in after if isinstance(entry.get("entry_id"), str)}
    if after_ids != before_ids:
        raise InstallerError(
            ERROR_HA_READY,
            "config-flow smoke left persistent Controlel config entries",
        )
    _append_log(log_path, "Controlel config-flow smoke OK")


def restart_ha(services: InstallerServices, log_path: Path, container: str) -> None:
    # Prefer Supervisor CLI when present; fall back to docker restart.
    code, _, _ = _logged_command(services, log_path, ["ha", "core", "restart"])
    if code != 0:
        code, _, _ = _logged_command(services, log_path, ["docker", "restart", container])
        if code != 0:
            raise InstallerError(ERROR_HA_RESTART, "HA Core restart failed")
    wait_for_ha(services, log_path, container)
    smoke_controlel_config_flow(services, log_path)


def stage_bundle(bundle_path: Path, stage_dir: Path, log_path: Path) -> dict[str, Any]:
    if stage_dir.exists():
        shutil.rmtree(stage_dir)
    stage_dir.mkdir(parents=True, exist_ok=True)
    try:
        metadata = validate_ha_test_bundle(bundle_path)
    except HaTestBundleError as error:
        raise InstallerError(ERROR_BUNDLE, str(error)) from error
    with zipfile.ZipFile(bundle_path, "r") as archive:
        for info in archive.infolist():
            name = info.filename
            if name.endswith("/") or ".." in Path(name).parts:
                raise InstallerError(ERROR_BUNDLE, f"unsafe archive member: {name}")
            target = stage_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(info))
    _append_log(log_path, f"staged bundle build_id={metadata['build_id']}")
    _append_log(
        log_path,
        "installer_schema_version="
        f"{metadata.get('installer_schema_version')} "
        f"installer_sha256={metadata.get('installer_sha256')}",
    )
    return metadata


def validate_host_integration_zip(integration_zip: Path) -> None:
    """Validate the host-staged integration ZIP before any Core transfer."""
    if not integration_zip.is_file():
        raise InstallerError(ERROR_INTEGRATION, "integration ZIP missing after staging")
    try:
        with zipfile.ZipFile(integration_zip, "r") as archive:
            names = archive.namelist()
            if "manifest.json" not in names or HA_TEST_BUILD_MARKER not in names:
                raise InstallerError(ERROR_INTEGRATION, "integration ZIP is incomplete")
            for name in names:
                if ".." in Path(name).parts or name.startswith("/"):
                    raise InstallerError(ERROR_INTEGRATION, f"unsafe integration member: {name}")
    except zipfile.BadZipFile as error:
        raise InstallerError(ERROR_INTEGRATION, "integration ZIP is corrupt") from error


def verify_stage_hashes(config_root: Path, metadata: Mapping[str, Any]) -> None:
    """Verify transferred artifacts under a Core ``/config`` tree."""
    stage = config_root / "controlel-test" / ".stage"
    wheel = stage / str(metadata["core_wheel"])
    integration = stage / "controlel.zip"
    bundle_json = stage / "bundle.json"
    if not wheel.is_file():
        raise InstallerError(ERROR_CORE_INSTALL, "Core wheel missing inside HA container stage")
    if not integration.is_file():
        raise InstallerError(ERROR_INTEGRATION, "integration ZIP missing inside HA container stage")
    if not bundle_json.is_file():
        raise InstallerError(ERROR_BUNDLE, "bundle.json missing inside HA container stage")
    import hashlib

    wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    integration_digest = hashlib.sha256(integration.read_bytes()).hexdigest()
    if wheel_digest != metadata["core_wheel_sha256"]:
        raise InstallerError(ERROR_CORE_INSTALL, "Core wheel SHA-256 mismatch inside HA container")
    if integration_digest != metadata["integration_zip_sha256"]:
        raise InstallerError(ERROR_INTEGRATION, "integration ZIP SHA-256 mismatch inside HA container")


def apply_integration_replacement(config_root: Path) -> None:
    """Completely replace ``custom_components/controlel`` from container stage ZIP."""
    stage_zip = config_root / "controlel-test" / ".stage" / "controlel.zip"
    if not stage_zip.is_file():
        raise InstallerError(ERROR_INTEGRATION, "integration ZIP missing inside HA container stage")
    custom_components = config_root / "custom_components"
    custom_components.mkdir(parents=True, exist_ok=True)
    live = custom_components / DOMAIN
    new_dir = custom_components / f".{DOMAIN}.new"
    old_dir = custom_components / f".{DOMAIN}.old"
    if new_dir.exists():
        shutil.rmtree(new_dir)
    if old_dir.exists():
        shutil.rmtree(old_dir)
    new_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(stage_zip, "r") as archive:
            archive.extractall(new_dir)
    except zipfile.BadZipFile as error:
        shutil.rmtree(new_dir, ignore_errors=True)
        raise InstallerError(ERROR_INTEGRATION, "integration ZIP is corrupt inside HA container") from error
    if not (new_dir / HA_TEST_BUILD_MARKER).is_file():
        shutil.rmtree(new_dir, ignore_errors=True)
        raise InstallerError(ERROR_INTEGRATION, "integration extraction failed")
    if live.exists():
        shutil.move(str(live), str(old_dir))
    shutil.move(str(new_dir), str(live))
    if old_dir.exists():
        shutil.rmtree(old_dir)


def read_installed_identity(config_root: Path) -> tuple[str, str]:
    live = config_root / "custom_components" / DOMAIN
    marker_path = live / HA_TEST_BUILD_MARKER
    manifest_path = live / "manifest.json"
    if not marker_path.is_file() or not manifest_path.is_file():
        raise InstallerError(ERROR_VERIFY, "installed integration identity files missing")
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    build_id = marker.get("build_id")
    version = manifest.get("version")
    if not isinstance(build_id, str) or not build_id:
        raise InstallerError(ERROR_VERIFY, "installed build_id missing")
    if not isinstance(version, str) or not version:
        raise InstallerError(ERROR_VERIFY, "installed integration version missing")
    return build_id, version


def cleanup_allowlisted_controlel_storage(config_root: Path) -> list[str]:
    storage = config_root / ".storage"
    removed: list[str] = []
    if not storage.is_dir():
        return removed
    for path in sorted(storage.iterdir()):
        if not path.is_file():
            continue
        if is_allowlisted_controlel_storage_name(path.name):
            path.unlink()
            removed.append(path.name)
    return removed


def _docker_mkdir(services: InstallerServices, log_path: Path, container: str, path: str) -> None:
    code, _, _ = _logged_command(
        services,
        log_path,
        ["docker", "exec", container, "mkdir", "-p", path],
    )
    if code != 0:
        raise InstallerError(ERROR_HA_CONTAINER, f"cannot create container path {path}")


def _docker_cp_to_container(
    services: InstallerServices,
    log_path: Path,
    *,
    container: str,
    host_path: Path,
    container_path: str,
    error_code: str,
    error_message: str,
) -> None:
    if not host_path.exists():
        raise InstallerError(error_code, error_message)
    parent = str(PurePosixPath(container_path).parent)
    _docker_mkdir(services, log_path, container, parent)
    code, _, _ = _logged_command(
        services,
        log_path,
        ["docker", "cp", str(host_path), f"{container}:{container_path}"],
    )
    if code != 0:
        raise InstallerError(error_code, error_message)


def transfer_artifacts_to_container(
    services: InstallerServices,
    log_path: Path,
    *,
    container: str,
    host_stage_dir: Path,
    metadata: Mapping[str, Any],
) -> str:
    """Copy wheel, integration ZIP, and bundle.json into the Core container."""
    wheel_name = str(metadata["core_wheel"])
    host_wheel = host_stage_dir / CORE_DIR / wheel_name
    host_integration = host_stage_dir / INTEGRATION_ARCHIVE
    host_bundle_json = host_stage_dir / "bundle.json"
    validate_host_integration_zip(host_integration)
    if not host_wheel.is_file():
        raise InstallerError(ERROR_CORE_INSTALL, "Core wheel missing after host staging")
    if not host_bundle_json.is_file():
        # Reconstruct minimal bundle.json for container-side verification.
        host_bundle_json.write_text(
            json.dumps(dict(metadata), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    _docker_mkdir(services, log_path, container, CONTAINER_STAGE_DIR)
    container_wheel = f"{CONTAINER_STAGE_DIR}/{wheel_name}"
    _docker_cp_to_container(
        services,
        log_path,
        container=container,
        host_path=host_wheel,
        container_path=container_wheel,
        error_code=ERROR_CORE_INSTALL,
        error_message="failed to copy Core wheel into HA container",
    )
    _docker_cp_to_container(
        services,
        log_path,
        container=container,
        host_path=host_integration,
        container_path=CONTAINER_INTEGRATION_ZIP,
        error_code=ERROR_INTEGRATION,
        error_message="failed to copy integration ZIP into HA container",
    )
    _docker_cp_to_container(
        services,
        log_path,
        container=container,
        host_path=host_bundle_json,
        container_path=CONTAINER_BUNDLE_JSON,
        error_code=ERROR_BUNDLE,
        error_message="failed to copy bundle.json into HA container",
    )
    _append_log(log_path, f"transferred artifacts into {container}:{CONTAINER_STAGE_DIR}")
    return container_wheel


def verify_container_stage_artifacts(
    services: InstallerServices,
    log_path: Path,
    *,
    container: str,
    metadata: Mapping[str, Any],
) -> None:
    """Verify SHA-256 of transferred artifacts inside the Core container."""
    script = f"""
# CONTROLEL_ACTION=verify_stage
import hashlib, json, pathlib, sys
stage = pathlib.Path({CONTAINER_STAGE_DIR!r})
meta = json.loads((stage / "bundle.json").read_text(encoding="utf-8"))
wheel = stage / meta["core_wheel"]
integration = stage / "controlel.zip"
expected_wheel = {metadata["core_wheel_sha256"]!r}
expected_integration = {metadata["integration_zip_sha256"]!r}
if not wheel.is_file():
    print("missing-wheel", file=sys.stderr)
    raise SystemExit(2)
if not integration.is_file():
    print("missing-integration", file=sys.stderr)
    raise SystemExit(3)
wheel_digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
integration_digest = hashlib.sha256(integration.read_bytes()).hexdigest()
if wheel_digest != expected_wheel:
    print("wheel-hash-mismatch", file=sys.stderr)
    raise SystemExit(4)
if integration_digest != expected_integration:
    print("integration-hash-mismatch", file=sys.stderr)
    raise SystemExit(5)
print("OK")
"""
    code, stdout, stderr = _logged_command(
        services,
        log_path,
        ["docker", "exec", container, "python", "-c", script],
    )
    if code != 0 or stdout.strip() != "OK":
        detail = (stderr or stdout or "container stage verification failed").strip()
        if "missing-wheel" in detail or "wheel-hash-mismatch" in detail:
            raise InstallerError(ERROR_CORE_INSTALL, "Core wheel verification failed inside HA container")
        if "missing-integration" in detail or "integration-hash-mismatch" in detail:
            raise InstallerError(ERROR_INTEGRATION, "integration verification failed inside HA container")
        raise InstallerError(ERROR_BUNDLE, "container stage verification failed")


def install_core_wheel_in_container(
    services: InstallerServices,
    log_path: Path,
    *,
    container: str,
    container_wheel: str,
) -> None:
    code, _, _ = _logged_command(
        services,
        log_path,
        [
            "docker",
            "exec",
            container,
            "python",
            "-m",
            "pip",
            "install",
            "--force-reinstall",
            "--no-deps",
            container_wheel,
        ],
    )
    if code != 0:
        raise InstallerError(ERROR_CORE_INSTALL, "Core wheel installation failed")


def replace_integration_in_container(
    services: InstallerServices,
    log_path: Path,
    *,
    container: str,
) -> None:
    script = f"""
# CONTROLEL_ACTION=apply_integration
import shutil, zipfile
from pathlib import Path
stage_zip = Path({CONTAINER_INTEGRATION_ZIP!r})
custom_components = Path({CONTAINER_CUSTOM_COMPONENTS!r})
domain = {DOMAIN!r}
marker = {HA_TEST_BUILD_MARKER!r}
if not stage_zip.is_file():
    raise SystemExit("missing-integration")
custom_components.mkdir(parents=True, exist_ok=True)
live = custom_components / domain
new_dir = custom_components / f".{{domain}}.new"
old_dir = custom_components / f".{{domain}}.old"
if new_dir.exists():
    shutil.rmtree(new_dir)
if old_dir.exists():
    shutil.rmtree(old_dir)
new_dir.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(stage_zip, "r") as archive:
    archive.extractall(new_dir)
if not (new_dir / marker).is_file():
    shutil.rmtree(new_dir, ignore_errors=True)
    raise SystemExit("extract-failed")
if live.exists():
    shutil.move(str(live), str(old_dir))
shutil.move(str(new_dir), str(live))
if old_dir.exists():
    shutil.rmtree(old_dir)
print("OK")
"""
    code, stdout, stderr = _logged_command(
        services,
        log_path,
        ["docker", "exec", container, "python", "-c", script],
    )
    if code != 0 or stdout.strip() != "OK":
        raise InstallerError(ERROR_INTEGRATION, "integration replacement failed inside HA container")
    _append_log(log_path, f"replaced {CONTAINER_LIVE_INTEGRATION}")


def verify_installed_identity_in_container(
    services: InstallerServices,
    log_path: Path,
    *,
    container: str,
    metadata: Mapping[str, Any],
) -> None:
    script = f"""
# CONTROLEL_ACTION=verify_install
import json
from pathlib import Path
live = Path({CONTAINER_LIVE_INTEGRATION!r})
marker = json.loads((live / {HA_TEST_BUILD_MARKER!r}).read_text(encoding="utf-8"))
manifest = json.loads((live / "manifest.json").read_text(encoding="utf-8"))
print(marker.get("build_id", ""))
print(manifest.get("version", ""))
"""
    code, stdout, _ = _logged_command(
        services,
        log_path,
        ["docker", "exec", container, "python", "-c", script],
    )
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if code != 0 or len(lines) < 2:
        raise InstallerError(ERROR_VERIFY, "installed integration identity files missing")
    if lines[0] != metadata["build_id"]:
        raise InstallerError(ERROR_VERIFY, "installed build_id does not match bundle")
    if lines[1] != metadata["integration_test_version"]:
        raise InstallerError(ERROR_VERIFY, "installed integration version does not match bundle")
    code, stdout, _ = _logged_command(
        services,
        log_path,
        [
            "docker",
            "exec",
            container,
            "python",
            "-c",
            "import importlib.metadata as m; print(m.version('controlel'))",
        ],
    )
    if code != 0 or stdout.strip() != str(metadata["core_version"]):
        raise InstallerError(ERROR_VERIFY, "installed Core version does not match bundle")


def remove_allowlisted_controlel_storage_in_container(
    services: InstallerServices,
    log_path: Path,
    *,
    container: str,
) -> None:
    prefixes = (
        "controlel.setup.",
        "controlel.water_safety.state.",
        "controlel.water_safety.evidence.",
    )
    script = f"""
# CONTROLEL_ACTION=cleanup_storage
from pathlib import Path
storage = Path({CONTAINER_STORAGE_DIR!r})
prefixes = {prefixes!r}
removed = []
if storage.is_dir():
    for path in sorted(storage.iterdir()):
        if path.is_file() and any(path.name.startswith(prefix) and len(path.name) > len(prefix) for prefix in prefixes):
            path.unlink()
            removed.append(path.name)
print("OK")
print(len(removed))
"""
    code, stdout, _ = _logged_command(
        services,
        log_path,
        ["docker", "exec", container, "python", "-c", script],
    )
    if code != 0 or not stdout.splitlines() or stdout.splitlines()[0].strip() != "OK":
        raise InstallerError(ERROR_CONFIG_RESET, "Controlel storage cleanup failed inside HA container")
    _append_log(log_path, "removed allowlisted Controlel storage inside HA container")


def cleanup_container_stage(
    services: InstallerServices,
    log_path: Path,
    *,
    container: str,
) -> None:
    code, _, _ = _logged_command(
        services,
        log_path,
        ["docker", "exec", container, "rm", "-rf", CONTAINER_STAGE_DIR],
    )
    if code != 0:
        _append_log(log_path, "warning: failed to remove container stage directory")


def remove_all_controlel_config_entries(
    services: InstallerServices,
    log_path: Path,
    *,
    settle_seconds: float = 2.0,
) -> None:
    entries = list_controlel_config_entries(services, log_path)
    for entry in entries:
        entry_id = entry.get("entry_id")
        if not isinstance(entry_id, str) or not entry_id:
            raise InstallerError(ERROR_CONFIG_RESET, "config entry missing entry_id")
        remove_config_entry(services, log_path, entry_id)
    services.sleep(settle_seconds)
    remaining = list_controlel_config_entries(services, log_path)
    if remaining:
        raise InstallerError(
            ERROR_CONFIG_RESET,
            f"Controlel config entries still present after removal: {len(remaining)}",
        )


def format_success(*, mode: str, build_id: str, config_status: str) -> str:
    label = "UPDATE" if mode == "up" else "CLEAN"
    return "\n".join(
        [
            "CONTROLEL TEST INSTALLER",
            f"MODE={label}",
            f"BUILD={build_id}",
            "BUNDLE=OK",
            "CORE=OK",
            "INTEGRATION=OK",
            f"CONFIG={config_status}",
            "HA=RESTARTED",
            "RESULT=OK",
        ]
    )


def format_diagnostics_success(*, file_path: Path) -> str:
    return "\n".join(
        [
            "CONTROLEL TEST DIAGNOSTICS",
            f"FILE={file_path.as_posix()}",
            "RESULT=OK",
        ]
    )


def format_error(*, code: str, message: str, log_path: Path) -> str:
    return "\n".join(
        [
            f"ERROR {code}: {message}",
            f"LOG={log_path}",
            "RESULT=ERROR",
        ]
    )


def _clip_text(value: str, *, limit: int = DIAG_MAX_SECTION_CHARS) -> str:
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return value[:limit] + f"\n... truncated {omitted} characters ...\n"


def _tail_text(value: str, *, max_lines: int = DIAG_LOG_TAIL_LINES) -> str:
    lines = value.splitlines()
    if len(lines) <= max_lines:
        return "\n".join(lines)
    omitted = len(lines) - max_lines
    return "\n".join([f"... omitted {omitted} earlier lines ...", *lines[-max_lines:]])


def _command_output(services: InstallerServices, argv: Sequence[str]) -> tuple[int, str, str]:
    code, stdout, stderr = services.run_command(argv, None)
    return code, stdout or "", stderr or ""


def _filter_interesting_lines(text: str, *, needles: Sequence[str]) -> str:
    matches = [line for line in text.splitlines() if any(needle.casefold() in line.casefold() for needle in needles)]
    if not matches:
        return "(none)"
    return _tail_text("\n".join(matches), max_lines=DIAG_LOG_TAIL_LINES)


def collect_diagnostics_report(
    services: InstallerServices,
    *,
    work_dir: Path,
    container: str,
) -> str:
    """Build a bounded, uploadable diagnostics text report. Read-only."""

    generated_at = datetime.now(UTC).isoformat()
    sections: list[str] = [
        "CONTROLEL HA TEST DIAGNOSTICS",
        f"generated_at={generated_at}",
        f"work_dir={work_dir}",
        f"container={container}",
        "",
    ]

    sections.append("== installed build identities ==")
    code, stdout, stderr = _command_output(
        services,
        [
            "docker",
            "exec",
            container,
            "python",
            "-c",
            (
                "from pathlib import Path; import json; "
                f"p=Path('/config/custom_components/{DOMAIN}/{HA_TEST_BUILD_MARKER}'); "
                "print(p.read_text(encoding='utf-8') if p.is_file() else 'MISSING')"
            ),
        ],
    )
    if code == 0 and stdout.strip() and stdout.strip() != "MISSING":
        sections.append(_clip_text(stdout.strip()))
    else:
        sections.append("ha_test_build.json=MISSING")
        if stderr.strip():
            sections.append(_clip_text(stderr.strip(), limit=2_000))

    code, stdout, stderr = _command_output(
        services,
        [
            "docker",
            "exec",
            container,
            "python",
            "-c",
            (
                "from pathlib import Path; import json; "
                f"p=Path('/config/custom_components/{DOMAIN}/manifest.json'); "
                "print(p.read_text(encoding='utf-8') if p.is_file() else 'MISSING')"
            ),
        ],
    )
    if code == 0 and stdout.strip() and stdout.strip() != "MISSING":
        sections.append("manifest.json=")
        sections.append(_clip_text(stdout.strip(), limit=4_000))
    else:
        sections.append("manifest.json=MISSING")

    sections.append("")
    sections.append("== core container state ==")
    inspect_format = (
        "Running={{.State.Running}} RestartCount={{.RestartCount}} "
        "OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}} "
        "Error={{.State.Error}} StartedAt={{.State.StartedAt}} FinishedAt={{.State.FinishedAt}} "
        "Status={{.State.Status}}"
    )
    code, stdout, stderr = _command_output(
        services,
        ["docker", "inspect", "--format", inspect_format, container],
    )
    sections.append(stdout.strip() if code == 0 and stdout.strip() else f"inspect_failed code={code}")
    if code != 0 and stderr.strip():
        sections.append(_clip_text(stderr.strip(), limit=2_000))

    sections.append("")
    sections.append("== docker container summary ==")
    code, stdout, stderr = _command_output(
        services,
        ["docker", "ps", "-a", "--format", "table {{.Names}}\t{{.Status}}\t{{.Image}}"],
    )
    sections.append(_clip_text(_tail_text(stdout if code == 0 else stderr)))

    sections.append("")
    sections.append(f"== home assistant core logs (tail {DIAG_LOG_TAIL_LINES}) ==")
    code, stdout, stderr = _command_output(
        services,
        ["docker", "logs", "--tail", str(DIAG_LOG_TAIL_LINES), container],
    )
    core_logs = stdout if code == 0 else ""
    if code != 0:
        sections.append(f"core_logs_unavailable code={code}")
        if stderr.strip():
            sections.append(_clip_text(stderr.strip(), limit=2_000))
    else:
        sections.append(_clip_text(_tail_text(core_logs)))

    sections.append("")
    sections.append(f"== supervisor logs (tail {DIAG_LOG_TAIL_LINES}, optional) ==")
    supervisor_logs = ""
    for candidate in ("hassio_supervisor", "homeassistant_supervisor", "supervisor"):
        code, stdout, stderr = _command_output(
            services,
            ["docker", "logs", "--tail", str(DIAG_LOG_TAIL_LINES), candidate],
        )
        if code == 0:
            supervisor_logs = stdout
            sections.append(f"supervisor_container={candidate}")
            sections.append(_clip_text(_tail_text(supervisor_logs)))
            break
    else:
        sections.append("supervisor_logs=MISSING")

    sections.append("")
    sections.append("== installer logs on host (optional) ==")
    current_log = work_dir / "install-current.log"
    if current_log.is_file():
        sections.append(f"install-current.log={current_log}")
        sections.append(_clip_text(_tail_text(current_log.read_text(encoding="utf-8", errors="replace"))))
    else:
        sections.append("install-current.log=MISSING")
    stamped = sorted(work_dir.glob("install-*.log"), key=lambda path: path.name, reverse=True)
    if stamped:
        latest = stamped[0]
        sections.append(f"latest_install_log={latest.name}")
        sections.append(_clip_text(_tail_text(latest.read_text(encoding="utf-8", errors="replace"))))
    else:
        sections.append("latest_install_log=MISSING")

    sections.append("")
    sections.append("== interesting Controlel / restart / OOM evidence ==")
    combined = "\n".join([core_logs, supervisor_logs])
    sections.append(
        _clip_text(
            _filter_interesting_lines(
                combined,
                needles=(
                    "controlel",
                    "Unable to remove unknown job listener",
                    "Restarting homeassistant",
                    "/core/restart",
                    "OOM",
                    "Out of memory",
                    "killed",
                    "Traceback",
                    "ERROR",
                    "WARNING",
                ),
            )
        )
    )

    report = "\n".join(sections).rstrip() + "\n"
    return _clip_text(report, limit=DIAG_MAX_FILE_CHARS)


def run_diagnostics(
    *,
    work_dir: Path,
    services: InstallerServices | None = None,
) -> int:
    """Collect read-only diagnostics; never mutates install or restarts HA."""

    services = services or default_services()
    work_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = work_dir / f"diag-{stamp}.log"
    output_path = work_dir / DIAGNOSTICS_FILENAME
    try:
        _append_log(log_path, f"work_dir={work_dir}")
        detect_docker(services, log_path)
        container = resolve_ha_container(services, log_path)
        report = collect_diagnostics_report(services, work_dir=work_dir, container=container)
        output_path.write_text(report, encoding="utf-8")
        _append_log(log_path, f"wrote {output_path} ({len(report)} chars)")
        print(format_diagnostics_success(file_path=output_path))
        return 0
    except InstallerError as error:
        _append_log(log_path, f"ERROR {error.code}: {error.message}")
        print(format_error(code=error.code, message=error.message, log_path=log_path), file=sys.stderr)
        return 1


def _prepare_paths(work_dir: Path) -> InstallerPaths:
    work_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = work_dir / f"install-{stamp}.log"
    current_log = work_dir / "install-current.log"
    bundle_path = work_dir / BUNDLE_FILENAME
    config_root = work_dir.parent
    paths = InstallerPaths(
        work_dir=work_dir,
        bundle_path=bundle_path,
        config_root=config_root,
        log_path=log_path,
    )
    _append_log(log_path, f"work_dir={work_dir}")
    try:
        if current_log.exists() or current_log.is_symlink():
            current_log.unlink()
        current_log.write_text(f"{log_path.name}\n", encoding="utf-8", newline="\n")
    except OSError:
        pass
    logs = sorted(work_dir.glob("install-*.log"), key=lambda item: item.name)
    for stale in logs[:-10]:
        try:
            stale.unlink()
        except OSError:
            pass
    return paths


def run_install(
    *,
    mode: str,
    work_dir: Path,
    services: InstallerServices | None = None,
) -> int:
    services = services or default_services()
    paths = _prepare_paths(work_dir)
    container = ""
    try:
        if mode not in {"up", "rm"}:
            raise InstallerError(ERROR_BUNDLE, f"unsupported mode: {mode}")
        if not paths.bundle_path.is_file():
            raise InstallerError(ERROR_BUNDLE, f"missing bundle: {paths.bundle_path}")

        detect_docker(services, paths.log_path)
        container = resolve_ha_container(services, paths.log_path)

        stage_dir = paths.work_dir / ".stage"
        metadata = stage_bundle(paths.bundle_path, stage_dir, paths.log_path)
        wheel_path = stage_dir / CORE_DIR / str(metadata["core_wheel"])
        integration_zip = stage_dir / INTEGRATION_ARCHIVE
        if not wheel_path.is_file() or not integration_zip.is_file():
            raise InstallerError(ERROR_BUNDLE, "staged bundle is incomplete")

        # Host/add-on staging is complete. Transfer into the Core container
        # namespace explicitly — never assume path equivalence.
        container_wheel = transfer_artifacts_to_container(
            services,
            paths.log_path,
            container=container,
            host_stage_dir=stage_dir,
            metadata=metadata,
        )
        verify_container_stage_artifacts(
            services,
            paths.log_path,
            container=container,
            metadata=metadata,
        )
        install_core_wheel_in_container(
            services,
            paths.log_path,
            container=container,
            container_wheel=container_wheel,
        )
        replace_integration_in_container(
            services,
            paths.log_path,
            container=container,
        )
        restart_ha(services, paths.log_path, container)
        verify_installed_identity_in_container(
            services,
            paths.log_path,
            container=container,
            metadata=metadata,
        )

        if mode == "rm":
            remove_all_controlel_config_entries(services, paths.log_path)
            remove_allowlisted_controlel_storage_in_container(
                services,
                paths.log_path,
                container=container,
            )
            remaining = list_controlel_config_entries(services, paths.log_path)
            if remaining:
                raise InstallerError(ERROR_CONFIG_RESET, "Controlel config entries reappeared")
            restart_ha(services, paths.log_path, container)
            remaining = list_controlel_config_entries(services, paths.log_path)
            if remaining:
                raise InstallerError(ERROR_CONFIG_RESET, "Controlel config entries remain after restart")
            config_status = "REMOVED"
        else:
            config_status = "PRESERVED"

        cleanup_container_stage(services, paths.log_path, container=container)
        print(format_success(mode=mode, build_id=str(metadata["build_id"]), config_status=config_status))
        return 0
    except InstallerError as error:
        _append_log(paths.log_path, f"ERROR {error.code}: {error.message}")
        print(format_error(code=error.code, message=error.message, log_path=paths.log_path), file=sys.stderr)
        return 1


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("up", "rm", "diag"), required=True)
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=Path("/homeassistant/config/controlel-test"),
        help="Directory containing controlel-ha-test.zip (SSH/add-on namespace)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.mode == "diag":
        return run_diagnostics(work_dir=arguments.work_dir)
    return run_install(mode=arguments.mode, work_dir=arguments.work_dir)


if __name__ == "__main__":
    raise SystemExit(main())
