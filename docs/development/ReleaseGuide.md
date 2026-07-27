# Core package release guide

## Release states

Controlel uses distinct release states:

1. **Editable source development** installs the current checkout with
   `python -m pip install -e .`. It is convenient but is not an artifact
   verification.
2. **Locally built artifact** is a wheel and sdist produced by the PEP 517
   backend under `dist/`.
3. **Verified wheel** has passed metadata, archive-content, and clean
   out-of-checkout installation checks.
4. **Published core package** is a verified artifact uploaded manually to the
   approved public package index and then independently installed from that
   index. Milestone 24B1 does not reach this state.
5. **Home Assistant exact dependency pin** is added only after public-index
   verification. Until then the custom-component manifest must keep
   `"requirements": []`.
6. **HACS readiness** additionally requires integration release packaging and
   HACS metadata. A verified or published core wheel alone does not provide
   HACS readiness.

## Distribution identity and version

The preferred distribution name and Python import package are both
`controlel`. A package-index availability check found no existing distribution
at the time of Milestone 24B1, but availability and project ownership must be
checked again immediately before publication.

The documented fallback distribution name is `controlel-core`. A fallback
distribution would still install the unchanged `controlel` import package.
Do not switch names or versions silently; any collision requires an explicit
review.

The first core release candidate is `0.1.0`. The single authoritative release
version is the static `project.version` in `pyproject.toml`. Runtime access uses
`controlel.__version__`, which reads installed distribution metadata through
`importlib.metadata`. An uninstalled source import reports
`0.0.0+uninstalled`; it never pretends to be a release.

The custom-component manifest version is a separate integration version. It is
not a second source for the core package version and need not remain identical
in later releases.

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

## Public release checklist

Milestone 24B1 stops after local and CI artifact verification. Before any first
publication:

- obtain explicit approval for Milestone 24B2;
- confirm the `controlel` package-index project is available or controlled by
  the project owner;
- use a package-index account controlled by the project owner;
- enable two-factor authentication;
- build from a clean, reviewed commit;
- rerun tests, build, Twine, archive-content, and clean-install checks;
- record wheel and sdist filenames and cryptographic hashes;
- verify package name, version, metadata, and filenames before upload;
- keep credentials, tokens, `.pypirc`, and release configuration out of the
  repository;
- upload only the approved artifacts manually;
- install `controlel==0.1.0` from the public index into another clean
  environment;
- confirm the installed files, version, and hashes correspond to the approved
  release.

No publication credentials, trusted publishing, upload workflow, or automatic
GitHub release belongs in Milestone 24B1. Trusted publishing can be considered
separately later.

## Exact Milestone 24B2 transition

After the public-index verification succeeds:

1. change the Home Assistant manifest to the exact approved pin
   `controlel==0.1.0` (or the approved fallback distribution);
2. use no ranges, wildcard, Git URL, branch, or local path;
3. remove editable core installation from HA framework CI where appropriate;
4. run HA framework tests against the published dependency;
5. run hassfest;
6. prepare a new custom-component version;
7. complete separate HACS release work.

The integration must never reference an unavailable distribution.
