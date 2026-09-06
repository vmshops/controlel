"""Obtain the manifest's exact public Core wheel and verify installed bytes."""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.metadata
import json
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[2]


def intended_version(root: Path = ROOT) -> str:
    requirements = json.loads((root / "custom_components/controlel/manifest.json").read_text())["requirements"]
    if len(requirements) != 1 or not requirements[0].startswith("controlel=="):
        raise RuntimeError("HA must declare one exact controlel==VERSION requirement")
    version = requirements[0].removeprefix("controlel==")
    if not version or any(char not in "0123456789." for char in version):
        raise RuntimeError(f"Invalid exact Core release version: {version!r}")
    return version


def download_public_wheel(version: str, directory: Path) -> Path:
    metadata_url = f"https://pypi.org/pypi/controlel/{version}/json"
    request = Request(metadata_url, headers={"User-Agent": "controlel-public-core-gate"})
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            metadata = json.load(response)
    except HTTPError as error:
        if error.code == 404:
            raise RuntimeError(
                f"Public Core {version} is not published on PyPI; HA release validation is blocked"
            ) from error
        raise
    if metadata["info"]["version"] != version:
        raise RuntimeError("PyPI metadata version does not match the HA pin")
    filename = f"controlel-{version}-py3-none-any.whl"
    matches = [
        item for item in metadata["urls"] if item["filename"] == filename and item["packagetype"] == "bdist_wheel"
    ]
    if len(matches) != 1 or matches[0].get("yanked", False):
        raise RuntimeError(f"Expected exactly one non-yanked public wheel: {filename}")
    artifact = matches[0]
    if not artifact["url"].startswith("https://files.pythonhosted.org/"):
        raise RuntimeError("Public wheel URL is outside the PyPI artifact host")
    with urlopen(artifact["url"], timeout=30) as response:  # noqa: S310
        data = response.read()
    digest = hashlib.sha256(data).hexdigest()
    if len(data) != artifact["size"] or digest != artifact["digests"]["sha256"]:
        raise RuntimeError("Downloaded public Core wheel does not match PyPI size/SHA-256")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / filename
    path.write_bytes(data)
    (directory / f"controlel-{version}-pypi.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Public wheel: {filename}; {len(data)} bytes; SHA-256 {digest}")
    return path


def verify_installed_wheel(wheel_path: Path, version: str) -> None:
    distribution = importlib.metadata.distribution("controlel")
    if distribution.version != version:
        raise RuntimeError(f"Installed Core {distribution.version} differs from HA pin {version}")
    with zipfile.ZipFile(wheel_path) as wheel:
        for name in wheel.namelist():
            if name.endswith("/") or name.endswith(".dist-info/RECORD"):
                continue
            installed = Path(distribution.locate_file(name))
            if not installed.is_file() or installed.read_bytes() != wheel.read(name):
                raise RuntimeError(f"Installed Core differs from public wheel: {name}")
    module = importlib.import_module("controlel")
    if Path(module.__file__).resolve() != Path(distribution.locate_file("controlel/__init__.py")).resolve():
        raise RuntimeError("Imported Core is shadowed by checkout or another installation")


def verify_ha_imports(root: Path = ROOT) -> None:
    missing = set()
    for path in (root / "custom_components/controlel").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.ImportFrom) or not node.module or not node.module.startswith("controlel."):
                continue
            try:
                module = importlib.import_module(node.module)
                for symbol in node.names:
                    if symbol.name != "*" and not hasattr(module, symbol.name):
                        missing.add(f"{node.module}.{symbol.name}")
            except ImportError as error:
                missing.add(f"{node.module}: {error}")
    if missing:
        raise RuntimeError("HA requires missing Core APIs: " + ", ".join(sorted(missing)))


def main(*, install: bool = False) -> None:
    version = intended_version()
    wheel = download_public_wheel(version, ROOT / "dist/public-core")
    if install:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "--no-deps", "--force-reinstall", str(wheel)],
            check=True,
        )
    else:
        verify_installed_wheel(wheel, version)
        verify_ha_imports()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="Install only the hash-verified public wheel")
    try:
        main(install=parser.parse_args().install)
    except RuntimeError as error:
        raise SystemExit(str(error)) from error
