# Home Assistant development composition

The development composition is a local-test artifact that keeps one integration
ZIP and its exact Core wheel together. It is intentionally non-publishable. The
source integration manifest requires immutable, published `controlel==0.16.0`;
the bundled integration copy alone is rewritten to candidate
`controlel==0.17.0` for an explicit local composition.

## Build

Run from WSL in the Windows worktree. Git identity is read through Windows Git
because this worktree's metadata contains Windows paths:

```bash
cd /mnt/c/GitHub/Controlel/controlel-core-017-mainline
source_ref="$(git.exe rev-parse HEAD | tr -d '\r')"
export SOURCE_DATE_EPOCH="$(git.exe show -s --format=%ct HEAD | tr -d '\r')"
.venv/bin/python scripts/packaging/build_development_composition.py \
  --source-ref "$source_ref"
```

The result is `dist/development/controlel-dev-0.17.0.zip`. Its
`composition.json` binds the SHA-256 of both contained artifacts:

- `core/controlel-0.17.0-py3-none-any.whl`
- `integration/controlel.zip`, whose copied manifest pins
  `controlel==0.17.0`

For an uncommitted worktree, append an honest label such as `+working-tree` to
`source_ref`; the artifact hashes remain the exact content identity.

## Install into a real Home Assistant test instance

Stop Home Assistant before replacing files. Extract the outer bundle to a
temporary directory, then:

```bash
HA_PYTHON=/path/to/home-assistant/python
HA_CONFIG=/path/to/home-assistant/config

"$HA_PYTHON" -m pip install --force-reinstall --no-deps \
  core/controlel-0.17.0-py3-none-any.whl
unzip -oq integration/controlel.zip -d "$HA_CONFIG/custom_components/controlel"
find "$HA_CONFIG/custom_components/controlel" -type d -name __pycache__ \
  -prune -exec rm -rf -- {} +
"$HA_PYTHON" -c \
  "import importlib.metadata; print(importlib.metadata.version('controlel'))"
```

The version check must print `0.17.0`. Start Home Assistant and confirm that the
development bundle loads integration `0.14.0` with its rewritten local
requirement `controlel==0.17.0`, then run the Setup Wizard smoke flow. The
source release manifest remains pinned to public `controlel==0.16.0`. A restart
of an existing Docker container retains
the wheel; recreating the container does not, so reinstall the wheel after a
container recreation.

Do not install this bundle through HACS and do not upload either artifact to
PyPI or GitHub Releases. Home Assistant OS does not expose a supported persistent
Python environment for manual wheels; use a disposable Container/Core test
instance for this unpublished composition.
