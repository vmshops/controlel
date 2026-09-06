# Home Assistant manual test bundle

Canonical, deterministic workflow for deploying the **current working tree** into a
Home Assistant OS test instance. Do not hand-copy wheels, unzip layouts, or guess
whether an old `0.17.0` / `0.14.0` build is still running.

## Build on Windows

From the repository root (dirty worktree is supported and expected):

```text
python scripts/packaging/build_ha_test_bundle.py
```

This always builds both:

- the current Controlel Core wheel from this working tree
- the current Home Assistant integration from this working tree

## Copy exactly these two files

```text
dist/ha-test/controlel-ha-test.zip
dist/ha-test/install-controlel-test.sh
```

to:

```text
/homeassistant/config/controlel-test/
```

Nothing else is required.

## Installer commands

Update (replace Core + integration, preserve Controlel config):

```bash
bash /homeassistant/config/controlel-test/install-controlel-test.sh --up
```

Clean Controlel (replace Core + integration, remove all Controlel config, leave
all other Home Assistant data alone):

```bash
bash /homeassistant/config/controlel-test/install-controlel-test.sh --rm
```

Collect bounded diagnostics into one uploadable file (no install mutation, no HA restart):

```bash
bash /homeassistant/config/controlel-test/install-controlel-test.sh --diag
```

Aliases `-up`, `-rm`, and `-diag` are accepted. There are no interactive prompts.

- `--up` = replace Core + integration, preserve Controlel config
- `--rm` = replace Core + integration, remove all Controlel config, leave all other HA data alone
- `--diag` = write `/homeassistant/config/controlel-test/controlel-diagnostics.txt` only

## Protection mode

Run this from **Advanced SSH & Web Terminal** with **Protection mode disabled**
(and the add-on restarted after changing that setting). If Docker is blocked, the
installer exits before changing anything:

```text
ERROR E_DOCKER: Docker unavailable. Disable Protection mode for Advanced SSH & Web Terminal and restart the app.
```

You do not need Docker commands, wheel filenames, config-entry IDs, or
`.storage` paths.

## Success output

Update:

```text
CONTROLEL TEST INSTALLER
MODE=UPDATE
BUILD=<build-id>
BUNDLE=OK
CORE=OK
INTEGRATION=OK
CONFIG=PRESERVED
HA=RESTARTED
RESULT=OK
```

Clean:

```text
CONTROLEL TEST INSTALLER
MODE=CLEAN
BUILD=<build-id>
BUNDLE=OK
CORE=OK
INTEGRATION=OK
CONFIG=REMOVED
HA=RESTARTED
RESULT=OK
```

Diagnostics:

```text
CONTROLEL TEST DIAGNOSTICS
FILE=/homeassistant/config/controlel-test/controlel-diagnostics.txt
RESULT=OK
```

Detailed command output is written under `/homeassistant/config/controlel-test/`.
On failure the console prints a short `ERROR <code>: ...`, a `LOG=` path, and
`RESULT=ERROR`.

`RESULT=OK` means Home Assistant has restarted **and** its API/config-flow
infrastructure can load Controlel (not merely that the Docker container is
running). If startup never reaches that point, the installer exits with
`ERROR E_HA_READY`.

## Build identity

The installer rewrites only the **bundled** integration manifest / version marker
to an HA-valid development version derived from the real source version plus a
content token. The repository source `manifest.json` and public/HACS packaging
are not modified. After install, diagnostics and `ha_test_build.json` show the
exact `BUILD` identity from the console output.

## Water Safety manual baseline (real HA)

Truthful hardware / UX coverage for the current single-area Water Safety baseline.
Automated tests are not a substitute for the items marked not yet verified.

### MANUALLY VERIFIED ON REAL HA

- configuration / activation
- runtime load
- WET detection
- WET notification delivery
- DRY / moisture-cleared detection
- DRY notification delivery
- no obvious repeated-WET notification spam
- physical siren actuation

### NOT YET MANUALLY VERIFIED

- physical shutoff valve actuation (no suitable valve available for manual testing)

## Known non-blocking follow-ups (checkpoint)

Recorded for later work; not part of this baseline freeze:

- Explicit Back / Cancel UX contract on every native section form (see
  `docs/architecture/UILayers.md`)
- `device_registry` deprecation warning in `canonical_runtime.py`
- Water multi-area and Heating multi-zone remain future scope
- Old wizard remains intentionally frozen / hidden
- Further Shadow / Simulation work remains future scope
