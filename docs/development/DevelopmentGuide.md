# Development guide

## Test environments

The ordinary development environment deliberately has no Home Assistant
dependency. Use these separate suites:

```text
# A. Core and all dependency-free repository tests
python -m pytest --ignore=tests/integrations/home_assistant/framework

# B. Dependency-free Home Assistant adapter tests only
python -m pytest tests/integrations/home_assistant \
  --ignore=tests/integrations/home_assistant/framework

# C. Real Home Assistant framework tests (from .venv-ha)
python -m pytest tests/integrations/home_assistant/framework
```

Suite C is pinned to Home Assistant `2026.7.3` and
`pytest-homeassistant-custom-component==0.13.347`. It requires Python 3.14.2 or
newer. Home Assistant framework dependencies live only in
`requirements/ha-test.txt`; they are not project dependencies.

## Create the Home Assistant environment

Run this on Linux or in WSL from the repository root:

```bash
python3.14 -m venv .venv-ha
./.venv-ha/bin/python -m pip install --upgrade pip
./.venv-ha/bin/python -m pip install --require-hashes \
  -r requirements/ha-test.txt
./.venv-ha/bin/python -m pip install --no-deps -e .
./.venv-ha/bin/python -m pytest \
  tests/integrations/home_assistant/framework
```

The editable install is intentional: the custom component imports the reusable
`controlel` package from this checkout. The local project must be installed
separately and must not be added to the generated lock.

Home Assistant 2026.7.3 imports POSIX-only `fcntl` and `resource` modules in
its pytest bootstrap, so the standard framework command does not run in native
Windows Python. On a Windows workstation, enter a Python 3.14.2+ WSL
environment and use the Linux commands above. PowerShell path equivalents such
as the following are useful only for dependency inspection; the final pytest
command must run in Linux/WSL:

```powershell
py -3.14 -m venv .venv-ha
.\.venv-ha\Scripts\python.exe -m pip install --upgrade pip
.\.venv-ha\Scripts\python.exe -m pip install `
    --require-hashes `
    -r requirements\ha-test.txt
.\.venv-ha\Scripts\python.exe -m pip install --no-deps -e .
```

Do not use globally installed pytest or packaging tools.

## Regenerate the lock

Regenerate the canonical lock on Linux with Python 3.14.2 or newer. Platform
markers in the Home Assistant Bluetooth dependency graph differ between Linux
and Windows.

```bash
python3.14 -m venv .venv-ha
./.venv-ha/bin/python -m pip install --upgrade pip
./.venv-ha/bin/python -m pip install pip-tools==7.6.0
./.venv-ha/bin/python -m piptools compile \
  --allow-unsafe \
  --generate-hashes \
  --output-file=requirements/ha-test.txt \
  requirements/ha-test.in
./.venv-ha/bin/python -m pip install \
  --require-hashes \
  -r requirements/ha-test.txt
```

`--allow-unsafe` is required because the resolved test graph pins `pip`
through `pipdeptree`. Review both direct pins and the complete diff whenever
the lock is regenerated. Never add an editable checkout to the lock.

## Hassfest

The dedicated `.github/workflows/hassfest.yml` workflow validates the manifest,
configuration-flow strings, translations, and Repairs issue translations with
the immutable approved hassfest action revision. For local validation, use a
Home Assistant core source checkout (the PyPI wheel does not include the
hassfest scripts):

```bash
python3 -m script.hassfest --action validate \
  --integration-path /absolute/path/to/controlel/custom_components/controlel
```

Framework compatibility is not HACS readiness. The core is not published,
`custom_components/controlel/manifest.json` intentionally contains
`"requirements": []`, and publishing plus manifest dependency work remains a
later milestone.

## Core artifact validation

Core packaging uses a separate `.venv-package` environment with the exact
development tools in `requirements/package-test.txt`. It does not add build or
Twine to the core runtime dependencies.

```text
python -m pip install -r requirements/package-test.txt
python -m build
python -m twine check dist/*
python scripts/packaging/validate_artifacts.py dist
python scripts/packaging/verify_clean_install.py dist
```

The last command creates a clean temporary environment and runs outside the
checkout. Detailed Windows commands, accepted archive contents, versioning,
publication security, and the future manifest transition are documented in
[ReleaseGuide.md](ReleaseGuide.md).
