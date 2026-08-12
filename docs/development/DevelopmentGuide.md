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

# C. Real Home Assistant framework tests with local core (from .venv-ha)
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

The editable install is intentional for the local-source composition: the
custom component imports the reusable `controlel` package from this checkout.
The local project must be installed separately and must not be added to the
generated lock.

For public dependency validation, create a separate environment and never
install the checkout as a distribution:

```bash
python3.14 -m venv .venv-ha-public
./.venv-ha-public/bin/python -m pip install --require-hashes \
  -r requirements/ha-test.txt
./.venv-ha-public/bin/python -m pip install \
  --no-cache-dir \
  --index-url https://pypi.org/simple \
  controlel==0.6.0
CONTROLEL_FRAMEWORK_COMPOSITION=public \
  ./.venv-ha-public/bin/python -m pytest \
  tests/integrations/home_assistant/framework
```

This environment loads `custom_components/controlel` from the checkout through
the normal Home Assistant custom-component test mechanism, but imports the core
from `site-packages`. It must not add `src` to `PYTHONPATH`.

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

Framework compatibility is separate from HACS release validation. The manifest
pins the published core as `controlel==0.6.0`; HACS metadata and deterministic
integration release packaging are validated without publishing anything.

## HACS release candidate

Build and independently validate the fixed-name release candidate from the
repository root:

```text
python scripts/packaging/build_hacs_release.py --version 0.8.2
python scripts/packaging/validate_hacs_release.py \
  dist/hacs/controlel.zip \
  --version 0.8.2 \
  --checksum dist/hacs/controlel.zip.sha256
```

The builder requires exactly one integration directory, exact version and
core dependency metadata, complete strings/translations, and an allowlisted
file set. It writes normalized deterministic archive metadata. The validator
re-checks layout, metadata, modes, timestamps, path safety, file content, and
secret-like patterns without trusting the builder.

Run `tests/packaging/test_hacs_release_contract.py` to prove determinism and
rejection behavior. Generated files remain below ignored `dist/hacs/`.

## Configuration and options development

The integration candidate version is `0.8.2`; its manifest pins the published,
immutable core `controlel==0.6.0`.

New-entry configuration defaults are 0.3/0.1 Â°C hysteresis and 10/5-minute
minimum on/off times. Legacy entries normalize missing values to zero.
New entries keep generated stable `sensor_id` and `zone_id` values in
config-entry data and mutable settings in options. Effective configuration is
legacy data merged with options, with options taking precedence except that
stable IDs can never be overridden.

The first-run basic form uses temperature and switch entity selectors and safe
defaults. Its optional advanced step exposes explicit IDs, normalized safety
times, a Basic/Detailed/Debug diagnostic profile, optional Debug expiry, and
custom service bindings. Existing entries use a two-step Options Flow. New
entries store Basic; legacy entries missing the profile resolve to Detailed
with a 60-minute Debug duration, without a setup-time migration write. Tests
cover legacy entries and repeated options updates that unload the old runtime
before constructing the replacement.

## Operational snapshot development

`operational.py` is the integration-side observation contract. It is immutable
and read-only to entities: it mirrors existing runtime/host results and never
decides demand or dispatches commands. Meaningful updates increment a revision
and immediately deliver one consistent snapshot to subscribers. A separate
integration-owned observability controller refreshes active countdown
subscribers only: never periodically in Basic, every 10 seconds in Detailed,
and every second in Debug. Core scheduler callbacks still provide exact
control-deadline behavior. The trace is an in-memory deque capped at
20/100/500 records by profile and is cleared on reconstruction.

Framework tests assert one stable deterministic entity set using
`<config_entry_id>_<entity_key>`, entity categories, profile/rename/reload
stability, truthful inactive countdown availability, diagnostics allowlisting,
and normal unload behavior.

## Core artifact validation

Core packaging uses a separate `.venv-package` environment with the exact
development tools in `requirements/package-test.txt`. It does not add build or
Twine to the core runtime dependencies.

```text
python -m pip install -r requirements/package-test.txt
python scripts/packaging/build_core_release.py
python -m twine check dist/*
python scripts/packaging/validate_artifacts.py dist
python scripts/packaging/verify_clean_install.py dist
```

The deterministic builder runs the configured PEP 517 backend with
`SOURCE_DATE_EPOCH` set to the exact Git commit timestamp, then canonicalizes
only the sdist container metadata that setuptools otherwise stamps with build
time. Wheel and sdist file content remains the backend output. Run the builder
from a clean reviewed commit and require identical hashes across repeated clean
builds.

The last command creates a clean temporary environment and runs outside the
checkout. Detailed Windows commands, accepted archive contents, versioning,
publication security, and the published manifest dependency contract are documented in
[ReleaseGuide.md](ReleaseGuide.md).
