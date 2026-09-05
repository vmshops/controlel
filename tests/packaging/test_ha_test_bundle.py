"""Canonical Home Assistant manual-test bundle and installer contract."""

from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path

import pytest

from scripts.packaging.build_ha_test_bundle import build_ha_test_bundle
from scripts.packaging.ha_test_bundle import (
    BUNDLE_FILENAME,
    HA_TEST_BUILD_MARKER,
    INSTALLER_FILENAME,
    INSTALLER_SCHEMA_VERSION,
    HaTestBundleError,
    is_ha_valid_test_version,
    validate_ha_test_bundle,
)
from scripts.packaging.ha_test_installer import (
    CONTAINER_INTEGRATION_ZIP,
    CONTAINER_STAGE_DIR,
    DIAG_LOG_TAIL_LINES,
    DIAG_MAX_FILE_CHARS,
    DIAGNOSTICS_FILENAME,
    ERROR_CONFIG_RESET,
    ERROR_CORE_INSTALL,
    ERROR_DOCKER,
    ERROR_HA_READY,
    ERROR_INTEGRATION,
    InstallerServices,
    apply_integration_replacement,
    collect_diagnostics_report,
    format_diagnostics_success,
    format_success,
    run_diagnostics,
    run_install,
    validate_host_integration_zip,
    verify_stage_hashes,
)

ROOT = Path(__file__).parents[2]
CORE_VERSION = "0.17.0"


def _core_wheel(path: Path, *, version: str = CORE_VERSION) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    wheel = path / f"controlel-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            f"controlel-{version}.dist-info/METADATA",
            f"Metadata-Version: 2.4\nName: controlel\nVersion: {version}\n",
        )
        archive.writestr("controlel/__init__.py", "")
    return wheel


def _build(tmp_path: Path, *, root: Path = ROOT) -> tuple[Path, dict[str, object]]:
    output_dir = tmp_path / "ha-test"
    metadata = build_ha_test_bundle(
        root=root,
        output_dir=output_dir,
        core_wheel=_core_wheel(tmp_path),
    )
    return output_dir, metadata


def test_canonical_build_creates_exactly_two_external_artifacts(tmp_path: Path) -> None:
    output_dir, metadata = _build(tmp_path)

    names = sorted(path.name for path in output_dir.iterdir() if path.is_file())
    assert names == [BUNDLE_FILENAME, INSTALLER_FILENAME]
    assert (output_dir / BUNDLE_FILENAME).is_file()
    assert (output_dir / INSTALLER_FILENAME).is_file()
    assert metadata["dirty"] is True or metadata["dirty"] is False
    assert metadata["core_version"] == CORE_VERSION
    assert is_ha_valid_test_version(str(metadata["integration_test_version"]))


def test_bundle_contains_core_integration_and_provenance(tmp_path: Path) -> None:
    output_dir, metadata = _build(tmp_path)
    validated = validate_ha_test_bundle(output_dir / BUNDLE_FILENAME)

    assert validated["build_id"] == metadata["build_id"]
    assert validated["source_commit"]
    assert validated["core_wheel_sha256"] == metadata["core_wheel_sha256"]
    assert validated["integration_zip_sha256"] == metadata["integration_zip_sha256"]
    assert validated["installer_schema_version"] == INSTALLER_SCHEMA_VERSION
    assert validated["installer_sha256"] == metadata["installer_sha256"]

    with zipfile.ZipFile(output_dir / BUNDLE_FILENAME) as bundle:
        names = set(bundle.namelist())
        assert "bundle.json" in names
        assert "integration/controlel.zip" in names
        assert any(name.startswith("core/") and name.endswith(".whl") for name in names)
        assert "installer/ha_test_installer.py" in names
        assert "installer/ha_test_bundle.py" in names
        with zipfile.ZipFile(io.BytesIO(bundle.read("integration/controlel.zip"))) as integration:
            assert "lifecycle_diagnostics.py" in integration.namelist()
            assert HA_TEST_BUILD_MARKER in integration.namelist()
            manifest = json.loads(integration.read("manifest.json"))
            assert manifest["version"] == metadata["integration_test_version"]
            const_text = integration.read("const.py").decode("utf-8")
            assert f'INTEGRATION_VERSION = "{metadata["integration_test_version"]}"' in const_text


def test_source_manifest_is_not_mutated_by_test_build(tmp_path: Path) -> None:
    manifest_path = ROOT / "custom_components" / "controlel" / "manifest.json"
    const_path = ROOT / "custom_components" / "controlel" / "const.py"
    before_manifest = manifest_path.read_bytes()
    before_const = const_path.read_bytes()

    _build(tmp_path)

    assert manifest_path.read_bytes() == before_manifest
    assert const_path.read_bytes() == before_const
    assert json.loads(before_manifest)["version"] == "0.14.0"


def test_corrupted_bundle_is_rejected_before_install(tmp_path: Path) -> None:
    output_dir, _metadata = _build(tmp_path)
    bundle = output_dir / BUNDLE_FILENAME
    raw = bytearray(bundle.read_bytes())
    raw[-20:] = b"\x00" * 20
    bundle.write_bytes(bytes(raw))

    with pytest.raises(HaTestBundleError):
        validate_ha_test_bundle(bundle)

    work = tmp_path / "config" / "controlel-test"
    work.mkdir(parents=True)
    shutil.copy2(bundle, work / BUNDLE_FILENAME)
    stale = work.parent / "custom_components" / "controlel"
    stale.mkdir(parents=True)
    stale.joinpath("stale_obsolete.py").write_text("# stale\n", encoding="utf-8")

    def run_command(argv, cwd=None):
        if argv[:2] == ["docker", "info"]:
            return 0, "", ""
        if argv[:2] == ["docker", "ps"]:
            return 0, "homeassistant\n", ""
        return 0, "", ""

    services = InstallerServices(
        run_command=run_command,
        http_exchange=lambda *args: (200, b"[]"),
        sleep=lambda _seconds: None,
        time_monotonic=lambda: 0.0,
        env={"SUPERVISOR_TOKEN": "token"},
    )
    assert run_install(mode="up", work_dir=work, services=services) == 1
    assert (stale / "stale_obsolete.py").is_file()


def test_new_runtime_module_is_included_without_hacs_allowlist_update(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    shutil.copytree(ROOT / "custom_components", root / "custom_components")
    shutil.copy2(ROOT / "pyproject.toml", root / "pyproject.toml")
    # Minimal git identity via monkeypatch is awkward; reuse real ROOT git by
    # placing only the integration override under a copied custom_components
    # while building against ROOT files for pyproject/git through explicit root
    # that still has .git — use a nested override instead.
    component = ROOT / "custom_components" / "controlel"
    probe_name = "_ha_test_probe_module.py"
    probe_path = component / probe_name
    assert not probe_path.exists()
    probe_path.write_text("# temporary packaging probe\n", encoding="utf-8")
    try:
        output_dir, _metadata = _build(tmp_path)
        with zipfile.ZipFile(output_dir / BUNDLE_FILENAME) as bundle:
            with zipfile.ZipFile(io.BytesIO(bundle.read("integration/controlel.zip"))) as integration:
                assert probe_name in integration.namelist()
    finally:
        probe_path.unlink(missing_ok=True)


def test_checksum_mismatch_is_detected(tmp_path: Path) -> None:
    output_dir, metadata = _build(tmp_path)
    bundle_path = output_dir / BUNDLE_FILENAME
    with zipfile.ZipFile(bundle_path, "r") as original:
        files = {name: original.read(name) for name in original.namelist()}
    payload = json.loads(files["bundle.json"])
    payload["core_wheel_sha256"] = "0" * 64
    files["bundle.json"] = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)
    bundle_path.write_bytes(buffer.getvalue())

    with pytest.raises(HaTestBundleError, match="Core wheel SHA-256 mismatch"):
        validate_ha_test_bundle(bundle_path)
    assert metadata["core_wheel_sha256"] != "0" * 64


def _installer_env(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    """Create separated SSH/add-on and Core container filesystem namespaces."""
    output_dir, metadata = _build(tmp_path / "build")
    # Advanced SSH & Web Terminal namespace (NOT the Core container).
    addon_root = tmp_path / "addon" / "homeassistant" / "config"
    work = addon_root / "controlel-test"
    work.mkdir(parents=True)
    shutil.copy2(output_dir / BUNDLE_FILENAME, work / BUNDLE_FILENAME)

    # Home Assistant Core container /config namespace (distinct path).
    container_config = tmp_path / "ha-container" / "config"
    other = container_config / "custom_components" / "other"
    other.mkdir(parents=True)
    other.joinpath("manifest.json").write_text('{"domain":"other"}\n', encoding="utf-8")
    stale = container_config / "custom_components" / "controlel"
    stale.mkdir(parents=True)
    stale.joinpath("stale_obsolete.py").write_text("# stale\n", encoding="utf-8")
    storage = container_config / ".storage"
    storage.mkdir()
    storage.joinpath("core.config_entries").write_text('{"version":1}\n', encoding="utf-8")
    storage.joinpath("controlel.setup.entry1").write_text("{}\n", encoding="utf-8")
    storage.joinpath("unrelated.thing").write_text("{}\n", encoding="utf-8")

    assert work.resolve() != container_config.resolve()
    assert not (addon_root / "custom_components" / "controlel").exists()
    return work, container_config, metadata


def _container_path(container_config: Path, absolute: str) -> Path:
    assert absolute.startswith("/config/")
    return container_config / absolute[len("/config/") :]


def _mock_services(
    container_config: Path,
    *,
    entries_before: list[dict[str, object]] | None = None,
    entries_after: list[dict[str, object]] | None = None,
    pip_fail: bool = False,
    restart_timeout: bool = False,
    docker_fail: bool = False,
    skip_docker_cp: bool = False,
    api_ready_after_polls: int = 0,
    handler_ready_after_polls: int = 0,
    handler_never_ready: bool = False,
    smoke_invalid_handler: bool = False,
    smoke_leaves_entry: bool = False,
    core_version: str = CORE_VERSION,
) -> tuple[InstallerServices, list[list[str]]]:
    entries_before = list(entries_before or [])
    entries_after = list(entries_after if entries_after is not None else [])
    state = {
        "removed": False,
        "t": 0.0,
        "api_polls": 0,
        "handler_polls": 0,
        "open_flows": {},
        "smoke_created_entry": False,
    }
    commands: list[list[str]] = []

    def run_command(argv, cwd=None):
        command = list(argv)
        commands.append(command)
        if command[:2] == ["docker", "info"]:
            if docker_fail:
                return 1, "", "permission denied while trying to connect to the Docker daemon"
            return 0, "", ""
        if command[:2] == ["docker", "ps"]:
            return 0, "homeassistant\n", ""
        if command[:2] == ["docker", "inspect"]:
            return 0, "true\n", ""
        if command[:2] == ["docker", "cp"]:
            if skip_docker_cp:
                return 1, "", "docker cp disabled for test"
            src = Path(command[2])
            _container_name, dest = command[3].split(":", 1)
            target = _container_path(container_config, dest)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
            return 0, "", ""
        if command[:3] == ["docker", "exec", "homeassistant"] and command[3:4] == ["mkdir"]:
            path = command[-1]
            _container_path(container_config, path).mkdir(parents=True, exist_ok=True)
            return 0, "", ""
        if command[:3] == ["docker", "exec", "homeassistant"] and command[3:5] == ["rm", "-rf"]:
            target = _container_path(container_config, command[-1])
            if target.exists():
                shutil.rmtree(target)
            return 0, "", ""
        if command[:3] == ["docker", "exec", "homeassistant"] and "pip" in command:
            wheel = command[-1]
            local_wheel = _container_path(container_config, wheel)
            if not local_wheel.is_file():
                return 1, "", f"No such file or directory: '{wheel}'"
            if pip_fail:
                return 1, "", "pip failed"
            return 0, "", ""
        if command[:3] == ["docker", "exec", "homeassistant"] and "-c" in command:
            code = command[command.index("-c") + 1]
            if "CONTROLEL_ACTION=verify_stage" in code:
                meta = json.loads(
                    (container_config / "controlel-test" / ".stage" / "bundle.json").read_text(encoding="utf-8")
                )
                try:
                    verify_stage_hashes(container_config, meta)
                except Exception as error:  # noqa: BLE001 - test harness maps installer failures
                    return 1, "", str(error)
                return 0, "OK\n", ""
            if "CONTROLEL_ACTION=apply_integration" in code:
                try:
                    apply_integration_replacement(container_config)
                except Exception as error:  # noqa: BLE001
                    return 1, "", str(error)
                return 0, "OK\n", ""
            if "CONTROLEL_ACTION=verify_install" in code:
                live = container_config / "custom_components" / "controlel"
                marker = json.loads((live / HA_TEST_BUILD_MARKER).read_text(encoding="utf-8"))
                manifest = json.loads((live / "manifest.json").read_text(encoding="utf-8"))
                return 0, f"{marker['build_id']}\n{manifest['version']}\n", ""
            if "CONTROLEL_ACTION=cleanup_storage" in code:
                storage = container_config / ".storage"
                removed = 0
                if storage.is_dir():
                    for path in list(storage.iterdir()):
                        name = path.name
                        if name.startswith(
                            ("controlel.setup.", "controlel.water_safety.state.", "controlel.water_safety.evidence.")
                        ):
                            path.unlink()
                            removed += 1
                return 0, f"OK\n{removed}\n", ""
            if "importlib.metadata" in code:
                return 0, f"{core_version}\n", ""
            return 0, "", ""
        if command[:3] == ["ha", "core", "restart"]:
            return 0, "", ""
        if command[:2] == ["docker", "restart"]:
            return 0, "", ""
        return 0, "", ""

    def _entries_payload():
        payload = entries_after if state["removed"] else entries_before
        if state["removed"]:
            payload = entries_after
        if state["smoke_created_entry"]:
            payload = list(payload) + [{"entry_id": "smoke-temp", "domain": "controlel"}]
        return payload

    def http_exchange(method, url, headers=None, body=None):
        if url.rstrip("/").endswith("/api/config"):
            state["api_polls"] += 1
            if state["api_polls"] <= api_ready_after_polls:
                return 503, b"starting"
            return 200, b'{"version":"2026.7.3"}'
        if method.upper() == "GET" and url.endswith("/config/config_entries/entry"):
            if state["api_polls"] <= api_ready_after_polls:
                return 503, b"starting"
            return 200, json.dumps(_entries_payload()).encode("utf-8")
        if method.upper() == "GET" and url.endswith("/config/config_entries/flow_handlers"):
            state["handler_polls"] += 1
            if handler_never_ready or state["handler_polls"] <= handler_ready_after_polls:
                return 200, json.dumps(["hue", "mqtt"]).encode("utf-8")
            return 200, json.dumps(["hue", "controlel", "mqtt"]).encode("utf-8")
        if method.upper() == "POST" and url.endswith("/config/config_entries/flow"):
            if smoke_invalid_handler:
                return 400, b'{"message":"Invalid handler specified"}'
            flow_id = "flow-smoke-1"
            state["open_flows"][flow_id] = True
            if smoke_leaves_entry:
                state["smoke_created_entry"] = True
                return 200, json.dumps(
                    {"type": "create_entry", "handler": "controlel", "flow_id": flow_id, "title": "x"}
                ).encode("utf-8")
            return 200, json.dumps(
                {
                    "type": "form",
                    "handler": "controlel",
                    "flow_id": flow_id,
                    "step_id": "user",
                }
            ).encode("utf-8")
        if method.upper() == "DELETE" and "/config/config_entries/flow/" in url:
            flow_id = url.rsplit("/", 1)[-1]
            state["open_flows"].pop(flow_id, None)
            return 200, b'{"message":"Flow aborted"}'
        if method.upper() == "DELETE" and "/config/config_entries/entry/" in url:
            state["removed"] = True
            return 200, b"{}"
        if url.rstrip("/").endswith("/api") or url.rstrip("/").endswith("/api/"):
            return 200, b"{}"
        return 200, b"{}"

    def time_monotonic():
        if restart_timeout:
            state["t"] += 1000.0
        else:
            state["t"] += 1.0
        return state["t"]

    services = InstallerServices(
        run_command=run_command,
        http_exchange=http_exchange,
        sleep=lambda _seconds: None,
        time_monotonic=time_monotonic,
        env={"SUPERVISOR_TOKEN": "token"},
    )
    return services, commands


def test_installer_refuses_without_docker(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(container_config, docker_fail=True)
    code = run_install(mode="up", work_dir=work, services=services)
    assert code == 1
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in work.glob("install-*.log"))
    assert ERROR_DOCKER in log_text
    assert (container_config / "custom_components" / "controlel" / "stale_obsolete.py").is_file()


def test_up_preserves_config_and_replaces_stale_integration(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    work, container_config, metadata = _installer_env(tmp_path)
    services, commands = _mock_services(
        container_config,
        entries_before=[{"entry_id": "abc", "domain": "controlel"}],
    )
    assert run_install(mode="up", work_dir=work, services=services) == 0
    out = capsys.readouterr().out
    assert "MODE=UPDATE" in out
    assert f"BUILD={metadata['build_id']}" in out
    assert "CONFIG=PRESERVED" in out
    assert "RESULT=OK" in out
    assert "pip" not in out.casefold()

    live = container_config / "custom_components" / "controlel"
    assert not (live / "stale_obsolete.py").exists()
    assert (live / HA_TEST_BUILD_MARKER).is_file()
    assert (container_config / "custom_components" / "other" / "manifest.json").is_file()
    assert (container_config / ".storage" / "core.config_entries").is_file()
    assert (container_config / ".storage" / "controlel.setup.entry1").is_file()
    # Stage cleaned on success inside Core container.
    assert not (container_config / "controlel-test" / ".stage").exists()
    # Add-on namespace was never treated as Core /config.
    assert not (work.parent / "custom_components" / "controlel" / HA_TEST_BUILD_MARKER).exists()

    cp_commands = [cmd for cmd in commands if cmd[:2] == ["docker", "cp"]]
    assert any(str(metadata["core_wheel"]) in " ".join(cmd) for cmd in cp_commands)
    assert any(cmd[-1].endswith(f"homeassistant:{CONTAINER_INTEGRATION_ZIP}") for cmd in cp_commands)
    pip_commands = [cmd for cmd in commands if "pip" in cmd]
    assert pip_commands
    assert pip_commands[0][-1].startswith(f"{CONTAINER_STAGE_DIR}/")
    assert pip_commands[0][-1].endswith(str(metadata["core_wheel"]))


def test_rm_removes_only_controlel_entries_and_allowlisted_storage(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    work, container_config, metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(
        container_config,
        entries_before=[
            {"entry_id": "abc", "domain": "controlel"},
            {"entry_id": "other", "domain": "hue"},
        ],
        entries_after=[],
    )
    assert run_install(mode="rm", work_dir=work, services=services) == 0
    out = capsys.readouterr().out
    assert "MODE=CLEAN" in out
    assert "CONFIG=REMOVED" in out
    assert f"BUILD={metadata['build_id']}" in out
    assert not (container_config / ".storage" / "controlel.setup.entry1").exists()
    assert (container_config / ".storage" / "unrelated.thing").is_file()
    assert (container_config / ".storage" / "core.config_entries").is_file()


def test_rm_fails_closed_when_entries_remain(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(
        container_config,
        entries_before=[{"entry_id": "abc", "domain": "controlel"}],
        entries_after=[{"entry_id": "abc", "domain": "controlel"}],
    )
    assert run_install(mode="rm", work_dir=work, services=services) == 1
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in work.glob("install-*.log"))
    assert ERROR_CONFIG_RESET in log_text


def test_namespaces_are_not_assumed_equivalent(tmp_path: Path) -> None:
    work, container_config, metadata = _installer_env(tmp_path)
    assert work.as_posix().endswith("homeassistant/config/controlel-test")
    assert container_config.resolve() != work.parent.resolve()
    services, commands = _mock_services(container_config)
    assert run_install(mode="up", work_dir=work, services=services) == 0
    assert any(cmd[:2] == ["docker", "cp"] for cmd in commands)
    host_stage_wheel = work / ".stage" / "core" / str(metadata["core_wheel"])
    assert host_stage_wheel.is_file()
    # Success cleans Core container stage; host stage may remain for diagnostics.
    assert not (container_config / "controlel-test" / ".stage").exists()
    # Installing into Core did not mutate the add-on namespace as if it were /config.
    assert not (work.parent / "custom_components").exists()


def test_missing_docker_copied_artifact_fails_before_live_replacement(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, commands = _mock_services(container_config, skip_docker_cp=True)
    assert run_install(mode="up", work_dir=work, services=services) == 1
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in work.glob("install-*.log"))
    assert ERROR_CORE_INSTALL in log_text
    assert (container_config / "custom_components" / "controlel" / "stale_obsolete.py").is_file()
    assert any(cmd[:2] == ["docker", "cp"] for cmd in commands)


def test_container_side_hashes_verified_before_mutation(tmp_path: Path) -> None:
    work, container_config, metadata = _installer_env(tmp_path)
    services, commands = _mock_services(container_config)
    assert run_install(mode="up", work_dir=work, services=services) == 0
    verify_cmds = [
        cmd for cmd in commands if "-c" in cmd and "CONTROLEL_ACTION=verify_stage" in cmd[cmd.index("-c") + 1]
    ]
    pip_cmds = [cmd for cmd in commands if "pip" in cmd]
    apply_cmds = [
        cmd for cmd in commands if "-c" in cmd and "CONTROLEL_ACTION=apply_integration" in cmd[cmd.index("-c") + 1]
    ]
    assert verify_cmds and pip_cmds and apply_cmds
    assert commands.index(verify_cmds[0]) < commands.index(pip_cmds[0])
    assert commands.index(pip_cmds[0]) < commands.index(apply_cmds[0])
    assert metadata["core_wheel_sha256"]


def test_missing_integration_zip_fails_before_replacement(tmp_path: Path) -> None:
    with pytest.raises(Exception) as raised:
        validate_host_integration_zip(tmp_path / "missing.zip")
    assert raised.value.code == ERROR_INTEGRATION  # type: ignore[attr-defined]


def test_invalid_integration_zip_fails_before_replacement(tmp_path: Path) -> None:
    bad = tmp_path / "bad.zip"
    bad.write_bytes(b"not-a-zip")
    with pytest.raises(Exception) as raised:
        validate_host_integration_zip(bad)
    assert raised.value.code == ERROR_INTEGRATION  # type: ignore[attr-defined]


def test_core_install_failure_is_deterministic(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(container_config, pip_fail=True)
    assert run_install(mode="up", work_dir=work, services=services) == 1
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in work.glob("install-*.log"))
    assert ERROR_CORE_INSTALL in log_text
    # Integration must not be replaced when Core install fails.
    assert (container_config / "custom_components" / "controlel" / "stale_obsolete.py").is_file()


def test_restart_timeout_is_deterministic(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(container_config, restart_timeout=True)
    assert run_install(mode="up", work_dir=work, services=services) == 1
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in work.glob("install-*.log"))
    assert ERROR_HA_READY in log_text


def test_waits_while_container_running_but_api_not_ready(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(container_config, api_ready_after_polls=2)
    assert run_install(mode="up", work_dir=work, services=services) == 0


def test_waits_until_controlel_flow_handler_appears(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(container_config, handler_ready_after_polls=2)
    assert run_install(mode="up", work_dir=work, services=services) == 0


def test_readiness_timeout_is_deterministic_e_ha_ready(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(container_config, handler_never_ready=True)
    assert run_install(mode="up", work_dir=work, services=services) == 1
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in work.glob("install-*.log"))
    assert ERROR_HA_READY in log_text
    assert "did not become ready" in log_text


def test_config_flow_handler_unavailable_does_not_claim_success(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(container_config, smoke_invalid_handler=True)
    assert run_install(mode="up", work_dir=work, services=services) == 1
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in work.glob("install-*.log"))
    assert ERROR_HA_READY in log_text
    assert "config-flow handler unavailable" in log_text


def test_config_flow_smoke_leaves_no_persistent_entry(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(container_config)
    assert run_install(mode="up", work_dir=work, services=services) == 0
    # Smoke created a temporary form flow and aborted it; entries unchanged.
    assert not any(
        "smoke-temp" in path.read_text(encoding="utf-8")
        for path in work.glob("install-*.log")
        if "left persistent" in path.read_text(encoding="utf-8")
    )


def test_config_flow_smoke_fails_if_entry_would_persist(tmp_path: Path) -> None:
    work, container_config, _metadata = _installer_env(tmp_path)
    services, _commands = _mock_services(container_config, smoke_leaves_entry=True)
    assert run_install(mode="up", work_dir=work, services=services) == 1
    log_text = "\n".join(path.read_text(encoding="utf-8") for path in work.glob("install-*.log"))
    assert ERROR_HA_READY in log_text
    assert "persistent Controlel config" in log_text


def test_installer_provenance_is_recorded(tmp_path: Path) -> None:
    output_dir, metadata = _build(tmp_path)
    assert metadata["installer_schema_version"] == INSTALLER_SCHEMA_VERSION
    assert isinstance(metadata["installer_sha256"], str)
    assert len(metadata["installer_sha256"]) == 64
    validated = validate_ha_test_bundle(output_dir / BUNDLE_FILENAME)
    assert validated["installer_sha256"] == metadata["installer_sha256"]
    # Distinct from content build id.
    assert metadata["installer_sha256"] != metadata["build_id"]


def test_console_success_output_is_minimal() -> None:
    text = format_success(mode="up", build_id="abc-dirty-123", config_status="PRESERVED")
    assert text.splitlines() == [
        "CONTROLEL TEST INSTALLER",
        "MODE=UPDATE",
        "BUILD=abc-dirty-123",
        "BUNDLE=OK",
        "CORE=OK",
        "INTEGRATION=OK",
        "CONFIG=PRESERVED",
        "HA=RESTARTED",
        "RESULT=OK",
    ]


def test_diagnostics_console_output_is_minimal() -> None:
    text = format_diagnostics_success(file_path=Path("/homeassistant/config/controlel-test/controlel-diagnostics.txt"))
    assert text.splitlines() == [
        "CONTROLEL TEST DIAGNOSTICS",
        "FILE=/homeassistant/config/controlel-test/controlel-diagnostics.txt",
        "RESULT=OK",
    ]


def test_diag_is_read_only_and_writes_bounded_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    work, container_config, metadata = _installer_env(tmp_path)
    live = container_config / "custom_components" / "controlel"
    live.mkdir(parents=True, exist_ok=True)
    (live / HA_TEST_BUILD_MARKER).write_text(
        json.dumps({"build_id": metadata["build_id"], "installer_sha256": metadata["installer_sha256"]}) + "\n",
        encoding="utf-8",
    )
    (live / "manifest.json").write_text(
        '{"domain":"controlel","version":"0.14.0.dev0+ha.test.abcd1234"}\n', encoding="utf-8"
    )
    (work / "install-current.log").write_text("install-20260101T000000Z.log\n", encoding="utf-8")
    (work / "install-20260101T000000Z.log").write_text("MODE=UPDATE BUILD=old\n", encoding="utf-8")

    huge_core_log = "\n".join(
        [
            "INFO unrelated noise",
            *[f"line {index}" for index in range(DIAG_LOG_TAIL_LINES + 50)],
            "INFO [homeassistant.core] Restarting homeassistant",
            "ERROR [homeassistant.core] Unable to remove unknown job listener",
            "ERROR [custom_components.controlel] sample controlel error",
            "WARNING Out of memory pressure noted",
        ]
    )
    supervisor_log = "\n".join(
        [
            "INFO /core/restart access from a0d7b954_ssh",
            "INFO Restarting homeassistant",
            "INFO ExitCode=0",
        ]
    )
    commands: list[list[str]] = []

    def run_command(argv, cwd=None):
        commands.append(list(argv))
        if argv[:2] == ["docker", "info"]:
            return 0, "", ""
        if argv[:2] == ["docker", "ps"] and "--filter" in argv:
            return 0, "homeassistant\n", ""
        if argv[:2] == ["docker", "ps"]:
            return 0, "NAMES\thomeassistant\tUp\n", ""
        if argv[:2] == ["docker", "inspect"]:
            return (
                0,
                (
                    "Running=true RestartCount=0 OOMKilled=false ExitCode=0 Error= "
                    "StartedAt=2026-09-05T09:00:00Z FinishedAt=0001-01-01T00:00:00Z Status=running\n"
                ),
                "",
            )
        if argv[:2] == ["docker", "logs"] and argv[-1] == "homeassistant":
            return 0, huge_core_log + "\n", ""
        if argv[:2] == ["docker", "logs"] and argv[-1] == "hassio_supervisor":
            return 0, supervisor_log + "\n", ""
        if argv[:2] == ["docker", "logs"]:
            return 1, "", "No such container"
        if argv[:3] == ["docker", "exec", "homeassistant"] and "ha_test_build.json" in argv[-1]:
            return 0, (live / HA_TEST_BUILD_MARKER).read_text(encoding="utf-8"), ""
        if argv[:3] == ["docker", "exec", "homeassistant"] and "manifest.json" in argv[-1]:
            return 0, (live / "manifest.json").read_text(encoding="utf-8"), ""
        return 0, "", ""

    services = InstallerServices(
        run_command=run_command,
        http_exchange=lambda *args: (_ for _ in ()).throw(AssertionError("diag must not call HA API")),
        sleep=lambda _seconds: (_ for _ in ()).throw(AssertionError("diag must not sleep/retry mutate")),
        time_monotonic=lambda: 0.0,
        env={},
    )
    before_stale = (container_config / "custom_components" / "controlel" / "stale_obsolete.py").read_text(
        encoding="utf-8"
    )
    assert run_diagnostics(work_dir=work, services=services) == 0
    out = capsys.readouterr().out
    assert "CONTROLEL TEST DIAGNOSTICS" in out
    assert DIAGNOSTICS_FILENAME in out
    assert "RESULT=OK" in out

    report_path = work / DIAGNOSTICS_FILENAME
    assert report_path.is_file()
    report = report_path.read_text(encoding="utf-8")
    assert len(report) <= DIAG_MAX_FILE_CHARS
    assert f'build_id": "{metadata["build_id"]}"' in report or metadata["build_id"] in report
    assert "RestartCount=0" in report
    assert "OOMKilled=false" in report
    assert "ExitCode=0" in report
    assert "Restarting homeassistant" in report
    assert "/core/restart" in report
    assert "Unable to remove unknown job listener" in report
    assert "omitted" in report.casefold()
    assert before_stale == (container_config / "custom_components" / "controlel" / "stale_obsolete.py").read_text(
        encoding="utf-8"
    )
    assert not any(cmd[:2] == ["docker", "restart"] for cmd in commands)
    assert not any(cmd[:2] == ["docker", "cp"] for cmd in commands)
    assert not any("pip" in cmd for cmd in commands)


def test_diag_tolerates_missing_optional_logs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    work, _container_config, _metadata = _installer_env(tmp_path)
    commands: list[list[str]] = []

    def run_command(argv, cwd=None):
        commands.append(list(argv))
        if argv[:2] == ["docker", "info"]:
            return 0, "", ""
        if argv[:2] == ["docker", "ps"]:
            return 0, "homeassistant\n", ""
        if argv[:2] == ["docker", "inspect"]:
            return (
                0,
                (
                    "Running=true RestartCount=1 OOMKilled=true ExitCode=137 Error= "
                    "StartedAt=x FinishedAt=y Status=exited\n"
                ),
                "",
            )
        if argv[:2] == ["docker", "logs"]:
            return 1, "", "No such container"
        if argv[:2] == ["docker", "exec"]:
            return 1, "", "missing"
        return 0, "", ""

    services = InstallerServices(
        run_command=run_command,
        http_exchange=lambda *args: (500, b""),
        sleep=lambda _seconds: None,
        time_monotonic=lambda: 0.0,
        env={},
    )
    assert run_diagnostics(work_dir=work, services=services) == 0
    report = (work / DIAGNOSTICS_FILENAME).read_text(encoding="utf-8")
    assert "supervisor_logs=MISSING" in report
    assert "install-current.log=MISSING" in report
    assert "OOMKilled=true" in report
    assert "RestartCount=1" in report
    assert "ha_test_build.json=MISSING" in report
    assert not any(cmd[:2] == ["docker", "restart"] for cmd in commands)
    assert "RESULT=OK" in capsys.readouterr().out


def test_collect_diagnostics_report_bounds_large_sections() -> None:
    services = InstallerServices(
        run_command=lambda argv, cwd=None: (
            (
                0,
                "x" * (DIAG_MAX_FILE_CHARS + 5_000),
                "",
            )
            if argv[:2] == ["docker", "logs"] and argv[-1] == "homeassistant"
            else (
                0,
                (
                    "Running=true RestartCount=0 OOMKilled=false ExitCode=0 Error= "
                    "StartedAt=a FinishedAt=b Status=running\n"
                ),
                "",
            )
            if argv[:2] == ["docker", "inspect"]
            else (0, "homeassistant\n", "")
            if argv[:2] == ["docker", "ps"]
            else (1, "", "missing")
        ),
        http_exchange=lambda *args: (200, b"[]"),
        sleep=lambda _seconds: None,
        time_monotonic=lambda: 0.0,
        env={},
    )
    report = collect_diagnostics_report(services, work_dir=Path("/tmp"), container="homeassistant")
    assert len(report) <= DIAG_MAX_FILE_CHARS
    assert "truncated" in report.casefold()


def test_ha_test_version_format_is_strict() -> None:
    assert is_ha_valid_test_version("0.14.0.dev0+ha.test.abc12345")
    assert not is_ha_valid_test_version("0.14.0")
    assert not is_ha_valid_test_version("0.14.0-dev")
    assert not is_ha_valid_test_version("0.14.0.dev0+ha.test.ABC")
