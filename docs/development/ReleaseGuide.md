# Release guide

## Integration 0.8.2 stabilization boundary

Core `0.6.0` and integration `0.8.1` are published and immutable. Integration
`0.8.2` keeps that exact core dependency and fixes the one installed-core
metadata lookup so it runs once through Home Assistant's executor. It also
adds the authoritative entity reference and a descriptor-key documentation
coverage contract. It changes no control policy, config-entry schema, or
entity identity.

## Milestone 30.2 core 0.6.0 boundary (historical)

Milestone 30.2 prepares core candidate `0.6.0` with source ownership and
capabilities, reported-source evidence, bounded reconciliation and recovery,
explicit operating modes, and reason-coded source-resilience diagnostics. It
also includes M30.2D runtime supervision, exclusive normal/failsafe command
authority, fatal fallback, generation quarantine, truthful state handover, and
a bounded default restart campaign of three attempts at fixed five-minute
intervals. It does not change the Home Assistant integration release boundary.
Published immutable `controlel==0.5.0` remains the current public core, and
integration `0.8.0` remains pinned to it. The integration may move to `0.6.0` only in a
later separate change after the core artifacts are published and independently
verified.

The 0.6.0 release-boundary commit changes core metadata, core packaging
contracts, and documentation only. It does not create artifacts, tag, upload,
publication, or a core GitHub Release.

The earlier pre-tag build bound to
`d7bfe426db90a21fed9cb9cae6591c310c0c9d42` predates M30.2D and is obsolete.
Neither those artifact bytes nor their hashes may be reused for publication.
Final core 0.6.0 artifacts must be rebuilt from the future exact reviewed
release `HEAD` after this boundary is committed, merged, and validated.

## Milestone 29 Phase A boundary

Milestone 29 Phase A prepared unpublished core candidate `0.5.0` with
multi-zone building-demand aggregation. Integration `0.7.0` remained unchanged
and continued to require immutable public `controlel==0.4.0`. The manifest did
not move to `0.5.0` until that core release was separately published and
verified. Phase A created validation artifacts only; it did not tag, upload,
publish, or release them.

## Milestone 28 sequencing

Phase A prepared core `0.4.0` while retaining the integration's public
`controlel==0.3.0` dependency. Phase B published and independently verified
immutable core `0.4.0` from annotated tag `core-v0.4.0`.

At the Milestone 28 boundary, Phase C set the manifest and
`INTEGRATION_VERSION` to `0.7.0`, pinned exactly `controlel==0.4.0`, and
validated separate local-source and public-PyPI compositions. M30.1C later
moved the integration dependency to published `controlel==0.5.0` after the
separate core release. The unpublished `0.7.0` candidate was never tagged or
released; `0.8.0` subsequently became the M30.1C integration boundary. Core tags
remain `core-vX.Y.Z`; integration tags remain `vX.Y.Z`.

## Milestone 26 sequencing

Phase A prepared core `0.2.0` and integration `0.4.0` while retaining the
published `controlel==0.1.0` manifest dependency. Phase B separately published
and independently verified immutable core `0.2.0`.

Phase C released integration `0.4.0` pinned to `controlel==0.2.0`. Milestone
26.1 prepared candidate `0.5.0` on the same immutable core, adding only
integration-owned observability. Tagging, release creation, and upload remained
separate explicitly approved actions.

## Release states

Controlel uses distinct release states:

1. **Editable source development** installs the current checkout with
   `python -m pip install -e .`. It is convenient but is not an artifact
   verification.
2. **Locally built artifact** is a wheel and sdist produced by the PEP 517
   backend under `dist/`.
3. **Verified wheel** has passed metadata, archive-content, and clean
   out-of-checkout installation checks.
4. **Published core package** is the verified `controlel==0.6.0` release on
   PyPI.
5. **Home Assistant exact dependency pin** is the integration contract
   `"requirements": ["controlel==0.6.0"]`.
6. **HACS readiness** additionally requires integration release packaging and
   HACS metadata. A verified or published core wheel alone does not provide
   HACS readiness.

## Distribution identity and version

The distribution name and Python import package are both `controlel`. Versions
`0.1.0`, `0.2.0`, `0.3.0`, `0.4.0`, `0.5.0`, and `0.6.0` are publicly available on PyPI and immutable.
PyPI versions are immutable; corrections always require a higher version.

The current core release is immutable `0.6.0`. Public-integration composition
checks and the Home Assistant manifest use that exact version.

The first core release is `0.1.0`. The single authoritative release
version is the static `project.version` in `pyproject.toml`. Runtime access uses
`controlel.__version__`, which reads installed distribution metadata through
`importlib.metadata`. An uninstalled source import reports
`0.0.0+uninstalled`; it never pretends to be a release.

The custom-component manifest version is a separate integration version. The
current candidate is `0.8.2`; it is not a second source for the core package
version and evolves independently. Candidate `0.8.2` is not published.

## Permanent tag namespaces

The tag namespaces are disjoint and permanent:

- `core-vX.Y.Z` is reserved for core/PyPI releases; `core-v0.2.0` is the
  namespace-correct tag name for core `0.2.0`.
- `vX.Y.Z` is reserved for Home Assistant integration releases. The existing
  integration tag `v0.2.0` must remain unchanged and must never be reused for
  the core package.

Core tags record PyPI source provenance. They do not create GitHub Releases in
this monorepo because HACS consumes the repository-wide GitHub Release stream.

## Published core 0.5.0 record

- Exact release commit: `c6791d444ab18d8c10f23bead53c87fe6d5adae4`.
- Annotated tag: `core-v0.5.0`.
- Wheel: `controlel-0.5.0-py3-none-any.whl`, 94,976 bytes, SHA-256
  `bb6e1e4a7b802e1ebc3d65bbd18c2111f6a4b992c3aaac56a3a823f272f45d09`.
- Sdist: `controlel-0.5.0.tar.gz`, 56,023 bytes, SHA-256
  `860cc9cd0a90050f61b0af9c456f2eec38375f1c89f545eca2bde5ccaccb9f28`.

The isolated public-composition CI verifies the exact wheel identity before
running the Home Assistant framework suite.

## Published core 0.4.0 record

- Exact release commit: `32e3a2c28d7de785b80e30ddf0852c0b48b02812`.
- Annotated tag: `core-v0.4.0`.
- Wheel: `controlel-0.4.0-py3-none-any.whl`, 63,889 bytes, SHA-256
  `0d2175b3ff7357ce8c6ec05bd7ad26553ef8ce85e652ecafc42185f317ea4d0d`.
- Sdist: `controlel-0.4.0.tar.gz`, 32,589 bytes, SHA-256
  `99b40d46e4e72eb2131bd432091132b214fa1967d43e74bf4346ac7c0bc4b5f9`.

The public wheel identity is enforced by the isolated public-composition CI
job. Corrections require a higher core version; these bytes must not be
replaced.

## Published core 0.3.0 provenance exception

Public PyPI `controlel==0.3.0` was built from a dirty Milestone 27 working
tree before the final core-only merge. A subsequent immutable-artifact audit
confirmed that its executable Python source, public API, dependencies, and
tested runtime behavior are equivalent to `core-v0.3.0`. Its byte differences
are limited to line endings, archive metadata, and README/long-description
text. The approved immutable public PyPI artifacts are:

- wheel `controlel-0.3.0-py3-none-any.whl`, SHA-256
  `a8756b0a1bc3efff7876439bbc12db42d3632ce2aa5bb1a4f8a74400fd76500e`;
- sdist `controlel-0.3.0.tar.gz`, SHA-256
  `f97bd8f1b129f7dcf2024ce4eeafbba5f0f4ffa49f6d0ee5704dddccfdf55289`.

These are the published hashes. Later clean tag rebuilds are verification
evidence and must not be represented as the bytes uploaded to PyPI.

This historical exception is the reason strict provenance-bound final release
preparation is now mandatory. An older candidate artifact must never be
uploaded merely because its embedded version matches a newly approved release.

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

.\.venv-package\Scripts\python.exe scripts\packaging\build_core_release.py
.\.venv-package\Scripts\python.exe -m twine check dist\*
.\.venv-package\Scripts\python.exe scripts\packaging\validate_artifacts.py dist
.\.venv-package\Scripts\python.exe scripts\packaging\verify_clean_install.py dist
```

The builder keeps setuptools as the configured PEP 517 backend. It derives
`SOURCE_DATE_EPOCH` from the exact Git commit unless the environment explicitly
provides it, then rewrites only sdist container metadata into a canonical
PAX-format tar stream and gzip header. Every member has a fixed timestamp,
owner, group, and portable mode; member order is sorted. File paths and file
content are unchanged. A release candidate must produce identical wheel and
sdist hashes across at least three clean builds.

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

## Strict final public core preparation

Ordinary development builds continue to use
`scripts/packaging/build_core_release.py`; they do not require a tag. Artifacts
eligible for a public upload must instead be produced by the strict interface:

```powershell
$version = "X.Y.Z"
$commit = "0123456789abcdef0123456789abcdef01234567"
$tag = "core-vX.Y.Z"
$output = "dist/core-final-X.Y.Z"

python scripts/packaging/prepare_final_core_release.py `
    --version $version `
    --commit $commit `
    --tag $tag `
    --output-dir $output

python scripts/packaging/validate_core_release_provenance.py `
    --provenance "$output/core-release-provenance.json" `
    --artifact-dir $output
```

The tag is optional for a pre-tag immutable verification, but a public release
must use the reviewed annotated `core-vX.Y.Z` tag. Lightweight tags are
explicitly rejected when `--tag` is supplied. The tag name must match the
release version and dereference to the exact requested commit.

### Cleanliness and immutable export policy

Strict preparation requires the invoking worktree to have exact `HEAD` at the
full 40-character requested commit and to be completely clean according to
`git status --porcelain --untracked-files=all`. This rejects tracked changes
and every non-ignored untracked file, including source and packaging inputs.
Ignored generated output such as `dist/` does not make the checkout dirty and
cannot contaminate the build because source is never copied from the checkout.

As a second independent protection, the tool exports the requested commit with
`git archive`, with checkout line-ending conversion disabled, into two fresh
temporary source roots. Both wheel/sdist pairs are built only there using the
commit timestamp as `SOURCE_DATE_EPOCH`. Repeated wheels and canonicalized
sdists must be byte-identical, and rebuilding a wheel from the canonical sdist
must reproduce the same wheel bytes. The explicit output directory must not
already exist, preventing an older candidate from remaining beside the final
artifacts.

### Provenance schema and upload binding

Successful preparation writes exactly one wheel, one sdist, and
`core-release-provenance.json`. Schema version 1 contains:

- tool name/version and schema version;
- package name and release version;
- exact commit, optional tag, tag type, and resolved tag commit;
- immutable export mechanism, commit/tree identity, and export SHA-256;
- deterministic build epoch and timestamp source;
- repeated-build and canonical-sdist rebuild verification results;
- wheel and sdist filenames, sizes, and SHA-256 hashes;
- the ordered two-file upload allowlist and final verification status.

`artifact_directory` is the manifest-relative value `.`. The validator requires
the supplied artifact directory to be the manifest's actual parent, rejects any
additional or substituted wheel/sdist, verifies filename, size, hash, package
metadata, and version, and prints an upload command naming only the two verified
artifacts. The provenance JSON contains no credentials or personal filesystem
paths.

## Future core release checklist

Published core versions `0.1.0`, `0.2.0`, `0.3.0`, `0.4.0`, `0.5.0`, and `0.6.0` are immutable. Every
future core publication follows this order:

1. implementation;
2. core-only merge;
3. green CI for the exact merged `HEAD`;
4. immutable release verification;
5. annotated `core-vX.Y.Z` tag at that exact commit;
6. strict final-release build from that exact tag and commit;
7. provenance and upload-binding verification;
8. PyPI upload of only those exact two verified artifact bytes;
9. public PyPI filename, size, hash, metadata, and clean-install verification.

Before executing the separately approved upload:

- obtain explicit approval for the future core release;
- confirm the `controlel` package-index project is controlled by the project
  owner;
- use a package-index account controlled by the project owner;
- enable two-factor authentication;
- build from a clean, reviewed exact commit using the strict final-release
  command, never from a retained candidate artifact;
- use only the `core-vX.Y.Z` tag namespace for core/PyPI provenance;
- rerun tests, build, Twine, archive-content, and clean-install checks;
- require identical repeated wheel/sdist bytes and an identical wheel rebuilt
  from the canonical sdist;
- record wheel and sdist filenames and cryptographic hashes;
- verify package name, version, metadata, and filenames before upload;
- keep credentials, tokens, `.pypirc`, and release configuration out of the
  repository;
- rerun the provenance upload-binding validator immediately before upload and
  upload only the two paths it names;
- install the new exact version from the public index into another clean
  environment;
- confirm the installed files, version, and hashes correspond to the approved
  release.

The repository still contains no publication credentials, upload workflow, or
automatic GitHub release. Packaging CI validates current source builds; it
must not upload rebuilt artifacts for an already published version.

## Home Assistant dependency contract

Integration `0.8.2` pins exactly `controlel==0.6.0`. CI keeps local editable
compatibility and public-package framework jobs isolated. The public job never
installs the repository as a distribution and proves the core resolves from
`site-packages`. Normal supported integration installation can obtain the core
automatically.

## Home Assistant integration release contract

Integration releases use a separate version stream:

- manifest and `INTEGRATION_VERSION`: `0.8.2`;
- future integration tag: `v0.8.2`;
- GitHub Release name:
  `Controlel Home Assistant Integration v0.8.2`;
- HACS asset: `controlel.zip`;
- checksum asset: `controlel.zip.sha256`;
- exact core dependency: `controlel==0.6.0`.

The published `v0.6.0` tag is immutable. The unpublished `v0.7.0` candidate was
never tagged or released. Integration tags always use
`vX.Y.Z`; core/PyPI provenance tags always use `core-vX.Y.Z`. Core GitHub
Releases must not be created in this monorepo because HACS consumes the
repository-wide release stream.

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
6. Create annotated tag `v0.8.2` at the reviewed commit.
7. Create GitHub Release
   `Controlel Home Assistant Integration v0.8.2`.
8. Attach `controlel.zip` and `controlel.zip.sha256`; download them again and
   verify their hashes.
9. Install through HACS in a clean supported Home Assistant instance.
10. Verify public core dependency installation, config flow, setup, unload,
    options updates, reload, restart, Repairs cleanup, rollback selection, and
    removal. Confirm existing `0.6.0` entries load without migration, retain
    all heating settings, and resolve a missing profile to Detailed.
11. Record commit, tag, filenames, hashes, Home Assistant/HACS versions, and
    results.

Never move a published tag or replace a published asset. A correction uses a
higher integration patch version.
