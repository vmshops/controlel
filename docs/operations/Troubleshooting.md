# Home Assistant integration troubleshooting

## Heating does not switch immediately

Check the heating enable/disable threshold, hysteresis demand,
source-control state, active lockout, lockout remaining, and deferred command
entities. A deferred command means the relevant minimum time has not elapsed.
Controlel uses successfully dispatched commands as its timing reference and
has no physical boiler feedback. It reevaluates current demand at expiry and
does not automatically retry a failed command.

Lockout history is intentionally unavailable after restart in this milestone.
The current switch state is never used to fabricate it.

## HACS cannot find the repository

Confirm that the exact custom-repository URL is
`https://github.com/vmshops/controlel` and the selected category is
**Integration**. The repository must be publicly accessible. Use the latest
published release; `0.5.0` remains an unpublished candidate.

If HACS downloaded files but Home Assistant cannot find Controlel, confirm
that `manifest.json` is at
`config/custom_components/controlel/manifest.json`, restart Home Assistant,
and refresh the browser cache. A nested path such as
`config/custom_components/controlel/custom_components/controlel` is invalid.

## Release checksum does not match

Do not install the archive. Download it again and compare its SHA-256 with both
the checksum asset and release notes. A published asset must never be silently
replaced. Report the mismatch through
`https://github.com/vmshops/controlel/issues`.

## Sensor input is ignored

The configured state must match the exact entity ID, contain a finite numeric
value, use `°C` or `°F`, and have an aware `last_updated`. Unknown,
unavailable, missing-unit, malformed, or timestamp-less states intentionally
produce no `Measurement`. An old current-state snapshot keeps its original
timestamp and is not refreshed at integration setup.

## Heat-source service failures

The adapter calls the configured service with blocking completion and an exact
`{"entity_id": ...}` target. A failure leaves applied core state unchanged,
logs an error, and creates or updates one stable recoverable Repairs issue. A
later successful heat-source call clears that issue. There is no automatic
retry and no physical-state confirmation.

The **Last command outcome** entity distinguishes a dispatched service call,
a suppressed duplicate, and recoverable or fatal failure. A dispatched state
still does not confirm the physical device moved. The recoverable failure
binary sensor clears with the owned Repairs issue after a later successful
call.

## Measurement, grace, and timeout visibility

Use **Measurement status**, **Measurement age**, **Safety state**, and
**Safety grace remaining** on the Controlel device. Unknown and unavailable
remain distinct; malformed values use `invalid_value`, and age/timestamp
admission can produce `stale` or `future_timestamp`. A valid recovery clears
the obsolete grace deadline and resumes normal demand evaluation. Diagnostics
can provide the current snapshot and bounded decision trace if the latest
reason needs more context.

If remaining-time entities change too often, select Basic or Detailed under
**Configure**. Basic is event-driven, Detailed updates active countdowns every
10 seconds, and Debug updates only active countdowns every second. An unavailable
deadline or remaining entity means its countdown is inactive. Debug shows an
Options Flow warning because active countdown history can increase Recorder
database volume; Controlel does not alter Recorder configuration.

## Fatal runtime failures

Scheduler installation/cancellation failure, clock regression, re-entrancy,
invalid provenance/configuration state, and unexpected programming failures
create or update one stable ERROR Repairs issue. The host stops accepting new
work and terminally shuts down behind already accepted runtime work. Reloading
constructs a new runtime; the stopped instance is never reused.

Before terminal cleanup, fatal shutdown makes at most one best-effort emergency
heating-off request unless the original failure was already a failed heating-off
operation. Diagnostics distinguish dispatched, failed, recursion-skipped, and
no-command-path outcomes. This records only the request outcome; it does not
claim the physical heat source is off.

## Reload and shutdown

Unload first rejects new state and timer submissions, removes listeners, lets
accepted serialized work finish, calls `ControlRuntime.stop()` on the
dedicated worker, and closes the executor. A late timer callback is harmless
because both the host acceptance gate and runtime generation checks reject it.
Normal unload/shutdown sends no heat-source command; the fatal-only emergency
behavior above is separate.

When **Configure** saves new options, this same unload-before-rebuild lifecycle
is used. If a renamed zone is not visible immediately, refresh the integration
page. Stable sensor and zone IDs intentionally do not follow display-name
changes.

After a HACS upgrade, restart Home Assistant rather than relying only on a
reload. Removing Controlel must start by removing its config entry, which
stops the runtime and clears its Repairs issues; remove the HACS repository
second.

## Core dependency installation

Integration `0.5.0` requires exactly `controlel==0.2.0`. Normal supported
installation lets Home Assistant obtain that dependency automatically; users
do not need to install it manually. If setup reports a missing core, confirm
that the environment can reach PyPI and that `python -m pip show controlel`
reports version `0.2.0`.

Local development may install the checkout with `python -m pip install
--no-deps -e .`. Public-package framework validation must use a different
environment, install `controlel==0.2.0` from PyPI, and resolve it from
`site-packages`.

## Framework test environment fails to start

Confirm the interpreter and exact packages first:

```text
python --version
python -m pip show homeassistant pytest-homeassistant-custom-component
```

The supported harness uses Python 3.14.2 or newer, Home Assistant `2026.7.3`,
and `pytest-homeassistant-custom-component==0.13.347`. Install the hashed lock
with `python -m pip install --require-hashes -r requirements/ha-test.txt`.
Then either install the checkout editable for the local composition or install
`controlel==0.2.0` from PyPI for the isolated public composition.

If native Windows reports `ModuleNotFoundError: No module named 'fcntl'` or
`No module named 'resource'`, run the framework suite in Linux or WSL. These
modules are imported by the pinned Home Assistant pytest bootstrap and are not
provided by Windows. Core and dependency-free adapter suites remain supported
in native Windows and do not require Home Assistant.

If a public-composition import resolves under the repository instead of
`site-packages`, recreate that environment and ensure neither an editable
installation nor `src` on `PYTHONPATH` is present. Do not add Home Assistant to
the ordinary project dependencies to repair an environment mix-up.
