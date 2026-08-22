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

Core 0.6.0 hosts may additionally provide explicit reported-source evidence,
source ownership/capabilities, recovery start, and operating-mode changes
through the serialized runtime boundary. `UNKNOWN` and `UNAVAILABLE` must be
forwarded truthfully. A host must not derive reported state from a successful
command or rebuild transition timestamps during restart/reload.

Reconciliation and recovery reuse the runtime's one-shot deadline ownership.
The default unknown-transition hold is five minutes, recovery is bounded to 30
seconds, corrective failure becomes retryable after 30 seconds, and manual
recovery defaults to two hours. Reload explicitly cancels manual recovery. No
host polling loop is required. `WATER_TARGET` is capability-gated intent only;
physical water-target dispatch remains unsupported in core 0.6.0.

M30.2D runtime supervision additionally requires host composition of a
`Scheduler`, a failsafe-runtime factory, and a normal-runtime restart factory.
The supervisor protects source-command authority when `ControlRuntime` fails
while the host process remains alive. It does not protect against complete Home
Assistant process failure, operating-system failure, power failure, or physical
hardware failure; those boundaries still require host, device, and hardware
safety mechanisms.

Integration 0.11.0 supplies that composition with the existing serialized HA
runtime executor and one-shot scheduler. The configured simple switch uses
explicit `CONTROLEL_OWNED` semantics, while HA state changes provide reported
controller evidence separately from command outcomes. Unload removes both
temperature and source subscriptions, cancels all adapter-owned timers, and
closes the command executor so a stale generation cannot dispatch.

## Custom-component packaging

The integration source is `custom_components/controlel`. The `0.12.0` integration
declares one config entry and requires published `controlel==0.12.0`.
The integration and core versions are independent, and the core is not
vendored into the component.

The repository root HACS manifest defines a release asset named
`controlel.zip`. Its archive root contains the files from
`custom_components/controlel` directly because HACS extracts the archive into
`config/custom_components/controlel`. The deterministic builder and independent
validator are:

```text
python scripts/packaging/build_hacs_release.py --version 0.12.0
python scripts/packaging/validate_hacs_release.py \
  dist/hacs/controlel.zip \
  --version 0.12.0 \
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

The host also owns one immutable operational snapshot source per runtime.
Runtime results, scheduler evaluations, and failure transitions update it on
the serialized host path. Home Assistant entities subscribe read-only. One
observability controller advances only active countdown presentation at the
configured profile cadence; Basic has no periodic presentation timer, Detailed
uses 10 seconds, and Debug uses one second. The independent control scheduler
still owns exact regulation deadlines. Unload closes the source and cancels
refresh ownership; reload constructs a new empty snapshot and a bounded
non-persistent decision trace.

## Development deployment

For local source development, copy or mount `custom_components/controlel` into
the configuration directory and install this repository into the same Python
environment:

```text
python -m pip install --no-deps -e /path/to/controlel
```

The editable install overrides the public core only for local development.
Public-package validation instead installs `controlel==0.12.0` into a separate
environment and never installs the checkout as a distribution.

For a supported custom-component deployment, Home Assistant can install the
exact manifest dependency automatically; users do not need to install the core
manually. The implementation is the published `0.12.0`
integration; deterministic release packaging remains a
separate release-boundary step. No default
HACS-store entry exists. End-user
installation instructions are in
[HomeAssistantInstallation.md](HomeAssistantInstallation.md).

Core versions `0.1.0`, `0.2.0`, `0.3.0`, `0.4.0`, `0.5.0`, `0.6.0`, and `0.7.0` are immutable
public releases. Any core correction requires a new version; never rebuild
and re-upload an existing version. See the
[release guide](../development/ReleaseGuide.md) for its exact source commit and
published hashes.

Core `0.12.0` is public and immutable. The integration `0.12.0`
installs exactly `controlel==0.12.0`; local and public-package CI compositions
validate the same activity-driven notification API boundary.
