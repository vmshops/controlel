# Release guide

## Release states

Controlel uses distinct release states:

1. **Editable source development** installs the current checkout with
   `python -m pip install -e .`. It is convenient but is not an artifact
   verification.
2. **Locally built artifact** is a wheel and sdist produced by the PEP 517
   backend under `dist/`.
3. **Verified wheel** has passed metadata, archive-content, and clean
   out-of-checkout installation checks.
4. **Published core package** is the verified `controlel==0.1.0` release on
   PyPI.
5. **Home Assistant exact dependency pin** is the integration contract
   `"requirements": ["controlel==0.1.0"]`.
6. **HACS readiness** additionally requires integration release packaging and
   HACS metadata. A verified or published core wheel alone does not provide
   HACS readiness.

## Distribution identity and version

The distribution name and Python import package are both `controlel`. Version
`0.1.0` is publicly available on PyPI.

The first core release is `0.1.0`. The single authoritative release
version is the static `project.version` in `pyproject.toml`. Runtime access uses
`controlel.__version__`, which reads installed distribution metadata through
`importlib.metadata`. An uninstalled source import reports
`0.0.0+uninstalled`; it never pretends to be a release.

The custom-component manifest version is a separate integration version. It is
`0.1.1`, is not a second source for the core package version, and evolves
independently.

## Published core 0.1.0 record

- Distribution: `controlel`
- Version: `0.1.0`
- Exact release-source commit:
  `99fe58c1461fdb58fd3ed5b4fc49f300d3770a97`
- Preceding packaging commit:
  `d96f9f7bb21650c006fc8ef3dd9d7c30b41db76f`
- Wheel: `controlel-0.1.0-py3-none-any.whl`
- Wheel SHA-256:
  `262c1356b997da763d0edab5fe8397018ef50c89524a869b9ab5265b9d6ca16f`
- Sdist: `controlel-0.1.0.tar.gz`
- Sdist SHA-256:
  `af69f97fdfab306130991b73a3caeac510b6c6475eadecc023818eb40c01fcd4`
- Public-index verification date: 2026-07-27

The classifier correction in the exact release-source commit is part of the
published artifacts; the release did not come from the preceding packaging
commit alone.

## Build configuration and contents

The core uses the explicit setuptools PEP 517 backend and discovers only
`controlel*` packages below `src`. Normal installation depends only on
Pydantic. Home Assistant, test tools, and packaging tools are not core runtime
dependencies.

The wheel contains:

- `controlel` modules;
- distribution metadata and the included license.

It must not contain the custom component, tests, HA dependency locks,
workflows, documentation trees, virtual environments, caches, or credentials.
`py.typed` is deliberately deferred: annotations exist, but Milestone 24B1
does not declare a supported public PEP 561 typing interface.

The intentionally narrow sdist contains:

- `pyproject.toml`;
- `README.md`;
- `LICENSE`;
- `MANIFEST.in`;
- `PKG-INFO`;
- generated `setup.cfg` rebuild metadata;
- `src/controlel`;
- generated `src/controlel.egg-info` metadata needed to inspect and rebuild the
  distribution.

Repository tests, custom components, docs, workflows, requirement locks,
virtual environments, caches, credentials, and local build output are
excluded.

## Windows build and validation

Use Python 3.14 and a dedicated environment. Remove only repository-local build
outputs before validation:

```powershell
Remove-Item -Recurse -Force dist, build -ErrorAction SilentlyContinue
Get-ChildItem -Path src -Directory -Filter "*.egg-info" |
    Remove-Item -Recurse -Force
Get-ChildItem -Path . -Directory -Filter "*.egg-info" |
    Remove-Item -Recurse -Force

py -3.14 -m venv .venv-package
.\.venv-package\Scripts\python.exe -m pip install --upgrade pip
.\.venv-package\Scripts\python.exe -m pip install `
    -r requirements\package-test.txt

.\.venv-package\Scripts\python.exe -m build
.\.venv-package\Scripts\python.exe -m twine check dist\*
.\.venv-package\Scripts\python.exe scripts\packaging\validate_artifacts.py dist
.\.venv-package\Scripts\python.exe scripts\packaging\verify_clean_install.py dist
```

`verify_clean_install.py` creates a second temporary virtual environment,
installs the wheel by absolute path, and runs from outside the checkout. It
verifies the installed path, version, representative core objects and runtime,
and absence of Home Assistant and the custom component.

For manual inspection with a persistent clean environment:

```powershell
$repo = $PWD.Path
$wheel = (
    Get-ChildItem "$repo\dist\controlel-*.whl" |
    Select-Object -First 1
).FullName

py -3.14 -m venv .venv-wheel
.\.venv-wheel\Scripts\python.exe -m pip install --upgrade pip
.\.venv-wheel\Scripts\python.exe -m pip install $wheel

Push-Location $env:TEMP
& "$repo\.venv-wheel\Scripts\python.exe" -c `
    "import controlel; print(controlel.__version__, controlel.__file__)"
& "$repo\.venv-wheel\Scripts\python.exe" -c `
    "import importlib.util; assert importlib.util.find_spec('homeassistant') is None"
& "$repo\.venv-wheel\Scripts\python.exe" -c `
    "import importlib.util; assert importlib.util.find_spec('custom_components') is None"
Pop-Location
```

Do not run the full source-tree suite as an installed-wheel smoke test. The
installed test intentionally verifies a small representative package surface.

## Future core release checklist

Core `0.1.0` is immutable. Before any future core publication:

- obtain explicit approval for the future core release;
- confirm the `controlel` package-index project is controlled by the project
  owner;
- use a package-index account controlled by the project owner;
- enable two-factor authentication;
- build from a clean, reviewed commit;
- rerun tests, build, Twine, archive-content, and clean-install checks;
- record wheel and sdist filenames and cryptographic hashes;
- verify package name, version, metadata, and filenames before upload;
- keep credentials, tokens, `.pypirc`, and release configuration out of the
  repository;
- upload only the approved artifacts manually;
- install the new exact version from the public index into another clean
  environment;
- confirm the installed files, version, and hashes correspond to the approved
  release.

The repository still contains no publication credentials, upload workflow, or
automatic GitHub release. Packaging CI validates current source builds; it
must not upload rebuilt `0.1.0` artifacts or expect their hashes to reproduce
the immutable public files.

## Home Assistant dependency contract

Integration `0.1.1` pins exactly `controlel==0.1.0`. CI keeps local editable
compatibility and public-package framework jobs isolated. The public job never
installs the repository as a distribution and proves the core resolves from
`site-packages`. Normal supported integration installation can obtain the core
automatically.

## Home Assistant integration release contract

Integration releases use a separate version stream:

- manifest and `INTEGRATION_VERSION`: `0.1.1`;
- integration tag: `v0.1.1`;
- GitHub Release name:
  `Controlel Home Assistant Integration v0.1.1`;
- HACS asset: `controlel.zip`;
- checksum asset: `controlel.zip.sha256`;
- exact core dependency: `controlel==0.1.0`.

The repository is prepared for this release but no tag or GitHub Release
exists. Core provenance tags use `core-vX.Y.Z`, but core GitHub Releases must
not be created in this monorepo because HACS consumes the repository-wide
release stream.

The ZIP contains only files originating below
`custom_components/controlel`, placed directly at archive root. GitHub's
automatic source archives are not the HACS asset.

## Manual integration release checklist

Every remote step requires explicit approval:

1. Confirm a clean synchronized `main` and record its exact commit.
2. Confirm source, framework, hassfest, HACS, formatting, and release-artifact
   CI are green.
3. Build the archive twice and require byte-identical output.
4. Run the independent validator and manually inspect the member list.
5. Record the ZIP SHA-256.
6. Create annotated tag `v0.1.1` at the reviewed commit.
7. Create GitHub Release
   `Controlel Home Assistant Integration v0.1.1`.
8. Attach `controlel.zip` and `controlel.zip.sha256`; download them again and
   verify their hashes.
9. Install through HACS in a clean supported Home Assistant instance.
10. Verify public core dependency installation, config flow, setup, unload,
    reload, restart, Repairs cleanup, rollback selection, and removal.
11. Record commit, tag, filenames, hashes, Home Assistant/HACS versions, and
    results.

Never move a published tag or replace a published asset. A correction uses a
higher integration patch version.
