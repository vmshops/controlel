import hashlib
import io
import json
import zipfile
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from scripts.ci import public_core_artifact as gate


def test_unpublished_pin_blocks_release_without_install(monkeypatch, tmp_path):
    def missing(*args, **kwargs):
        raise HTTPError("https://pypi.org", 404, "Not Found", {}, None)

    monkeypatch.setattr(gate, "urlopen", missing)
    with pytest.raises(RuntimeError, match="not published.*blocked"):
        gate.download_public_wheel("0.18.0", tmp_path)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("defect", ["hash", "size", "version", "yanked", "host", None])
def test_public_download_requires_exact_pypi_artifact(monkeypatch, tmp_path, defect):
    data = b"public wheel bytes"
    item = dict(
        filename="controlel-0.18.0-py3-none-any.whl",
        packagetype="bdist_wheel",
        size=len(data),
        digests={"sha256": hashlib.sha256(data).hexdigest()},
        url="https://files.pythonhosted.org/wheel",
        yanked=False,
    )
    metadata = {"info": {"version": "0.18.0"}, "urls": [item]}
    if defect == "hash":
        item["digests"]["sha256"] = "0" * 64
    elif defect == "size":
        item["size"] += 1
    elif defect == "version":
        metadata["info"]["version"] = "0.17.0"
    elif defect == "yanked":
        item["yanked"] = True
    elif defect == "host":
        item["url"] = "https://example.org/wheel"
    responses = iter([json.dumps(metadata).encode(), data])
    monkeypatch.setattr(gate, "urlopen", lambda *args, **kwargs: io.BytesIO(next(responses)))
    if defect:
        with pytest.raises(RuntimeError):
            gate.download_public_wheel("0.18.0", tmp_path)
        assert not list(tmp_path.glob("*.whl"))
    else:
        assert gate.download_public_wheel("0.18.0", tmp_path).read_bytes() == data


@pytest.mark.parametrize("defect", ["bytes", "version", "shadow", None])
def test_public_install_rejects_local_replacement(monkeypatch, tmp_path, defect):
    name = "controlel/__init__.py"
    path = tmp_path / name
    path.parent.mkdir()
    path.write_bytes(b"public")
    wheel_path = tmp_path / "core.whl"
    with zipfile.ZipFile(wheel_path, "w") as wheel:
        wheel.writestr(name, b"public")
    distribution = SimpleNamespace(
        version="0.17.0" if defect == "version" else "0.18.0", locate_file=lambda name: tmp_path / name
    )
    monkeypatch.setattr(gate.importlib.metadata, "distribution", lambda name: distribution)
    monkeypatch.setattr(
        gate.importlib,
        "import_module",
        lambda name: SimpleNamespace(
            __file__=str(tmp_path / "src/controlel/__init__.py" if defect == "shadow" else path)
        ),
    )
    if defect == "bytes":
        path.write_bytes(b"checkout")
    if defect:
        with pytest.raises(RuntimeError):
            gate.verify_installed_wheel(wheel_path, "0.18.0")
    else:
        gate.verify_installed_wheel(wheel_path, "0.18.0")


def test_required_ha_api_missing_is_actionable(monkeypatch, tmp_path):
    component = tmp_path / "custom_components/controlel"
    component.mkdir(parents=True)
    (component / "__init__.py").write_text(
        "from controlel.infrastructure.home_assistant import active_reference_for_module\n"
    )
    monkeypatch.setattr(gate.importlib, "import_module", lambda name: SimpleNamespace())
    with pytest.raises(RuntimeError, match="HA requires missing Core APIs:.*active_reference_for_module"):
        gate.verify_ha_imports(tmp_path)
