# Runtime Host Requirements

A deployable host must provide `Scheduler`, `ScheduledRuntimeFailureSink`, and
one serialized execution context for every `ControlRuntime` entry point. The
core does not supply these host resources. The Home Assistant custom component
provides one dedicated single-worker runtime executor and never runs core
operations directly on the Home Assistant event loop.

The Home Assistant host subscribes in buffering mode, reads and processes the
initial state, drains buffered events, and only then calls `start()`. Events
arriving during start remain buffered. This prevents zero-grace startup from
acting before available initial evidence is offered to the runtime. The host
submits `stop()` through the same serialized context during unload or Home
Assistant shutdown. Stop is terminal, cancels the owned deadline best-effort,
and sends no implicit heat-source command.

Scheduler adapters must treat deadlines as timezone-aware absolute wall-clock
times and deliver one-shot callbacks through the serialized host context.
They may convert the deadline to an initial monotonic delay. Backward wall-time
movement can cause the runtime to re-arm an apparently premature callback;
forward movement and suspend/resume can make callbacks late. Already queued
callbacks may arrive after cancellation and are neutralized by lifecycle and
generation checks.

The failure sink is the host boundary for scheduled clock, configuration,
scheduler, source, and programming failures. It must expose those failures
operationally. If the sink itself raises, that exception escapes the callback
boundary.

Sensor/zone repositories and EventBus subscriber configuration must remain
stable during active processing unless changed through the same serialized
context. Ports must not mutate runtime-owned stores.

All measurements, demands, safety state, applied state, timer ownership, and
lifecycle state are in memory and lost when the runtime instance or process is
replaced. Successful port return is not physical source-state confirmation.

## Custom-component packaging

The integration source is `custom_components/controlel`. Integration version
`0.2.0` declares one config entry and exactly requires `controlel==0.1.0`.
The integration and core versions are independent, and the core is not
vendored into the component.

The repository root HACS manifest defines a release asset named
`controlel.zip`. Its archive root contains the files from
`custom_components/controlel` directly because HACS extracts the archive into
`config/custom_components/controlel`. The deterministic builder and independent
validator are:

```text
python scripts/packaging/build_hacs_release.py --version 0.2.0
python scripts/packaging/validate_hacs_release.py \
  dist/hacs/controlel.zip \
  --version 0.2.0 \
  --checksum dist/hacs/controlel.zip.sha256
```

These commands only create ignored local release candidates. They do not
create tags, GitHub Releases, or publication state.

Stable sensor and zone IDs remain in config-entry data. Mutable settings are
stored in options; options override legacy data while IDs can never be
overridden. An empty options mapping therefore preserves an existing `0.1.1`
entry exactly. Saving options triggers the supported update listener. A reload
fully unloads the host, stops the runtime, closes its executor, snapshots the
configured temperature entity, and builds new repositories and one new
runtime. No measurements, demands, safety state, applied action, or physical
heat-source state are restored or inferred.

## Development deployment

For local source development, copy or mount `custom_components/controlel` into
the configuration directory and install this repository into the same Python
environment:

```text
python -m pip install --no-deps -e /path/to/controlel
```

The editable install overrides the public core only for local development.
Public-package validation instead installs `controlel==0.1.0` into a separate
environment and never installs the checkout as a distribution.

For a supported custom-component deployment, Home Assistant can install the
exact manifest dependency automatically; users do not need to install the core
manually. Integration `0.1.1` is published; metadata and deterministic release
packaging are prepared for the unpublished `0.2.0` candidate. No default
HACS-store entry exists. End-user
installation instructions are in
[HomeAssistantInstallation.md](HomeAssistantInstallation.md).

Core `0.1.0` is an immutable public release. Any core correction requires a new
version; never rebuild and re-upload `0.1.0`. See the
[release guide](../development/ReleaseGuide.md) for its exact source commit and
published hashes.
