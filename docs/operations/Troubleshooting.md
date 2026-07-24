# Home Assistant integration troubleshooting

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

## Fatal runtime failures

Scheduler installation/cancellation failure, clock regression, re-entrancy,
invalid provenance/configuration state, and unexpected programming failures
create or update one stable ERROR Repairs issue. The host stops accepting new
work and terminally shuts down behind already accepted runtime work. Reloading
constructs a new runtime; the stopped instance is never reused.

## Reload and shutdown

Unload first rejects new state and timer submissions, removes listeners, lets
accepted serialized work finish, calls `ControlRuntime.stop()` on the
dedicated worker, and closes the executor. A late timer callback is harmless
because both the host acceptance gate and runtime generation checks reject it.
Shutdown sends no heat-source command.

## Development installation

The custom-component manifest intentionally lists no package requirements.
The repository must be installed as a development package so
`custom_components.controlel` can import `controlel`. Home Assistant framework
tests require a separate environment containing Home Assistant and its custom
component test facilities; core tests remain independent.

## Framework test environment fails to start

Confirm the interpreter and exact packages first:

```text
python --version
python -m pip show homeassistant pytest-homeassistant-custom-component
```

The supported harness uses Python 3.14.2 or newer, Home Assistant `2026.7.3`,
and `pytest-homeassistant-custom-component==0.13.347`. Install the hashed lock
with `python -m pip install --require-hashes -r requirements/ha-test.txt`, then
install the checkout separately with `python -m pip install --no-deps -e .`.

If native Windows reports `ModuleNotFoundError: No module named 'fcntl'` or
`No module named 'resource'`, run the framework suite in Linux or WSL. These
modules are imported by the pinned Home Assistant pytest bootstrap and are not
provided by Windows. Core and dependency-free adapter suites remain supported
in native Windows and do not require Home Assistant.

If imports resolve to another checkout or an unexpected package version,
delete and recreate only `.venv-ha`, reinstall the lock, and repeat the
editable install. Do not add Home Assistant to the ordinary project
dependencies to repair an environment mix-up.
