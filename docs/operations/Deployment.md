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

The integration source is `custom_components/controlel`. Its manifest version
matches the project version `0.1.0`, declares one config entry, and has
`requirements: []`. It therefore assumes the local `controlel` core package is
already installed. The core is not vendored into the component. A future
release milestone must publish a distributable core and add an exact pinned
requirement before ordinary HACS deployment.

Configuration is immutable for a runtime lifetime. A reload fully unloads the
host, stops the runtime, closes its executor, and builds new repositories and
a new runtime. No measurements, demands, safety state, applied action, or
physical heat-source state are restored or inferred.

## Development deployment

Milestone 24A validates the existing component against Home Assistant
`2026.7.3`; it is not an ordinary HACS deployment. For a development Home
Assistant installation, copy or mount `custom_components/controlel` into the
configuration directory and install this repository into the same Python
environment:

```text
python -m pip install --no-deps -e /path/to/controlel
```

The editable install is required because the manifest deliberately declares
`"requirements": []` and the `controlel` core package has not been published.
The component does not vendor the core. Container and Home Assistant OS
deployments need a purpose-built development image or equivalent environment
that contains that editable installation; merely copying the component is not
sufficient.

Do not advertise this build as HACS-ready. Publishing and exactly pinning the
core package, release packaging, HACS metadata, and supported end-user
installation instructions remain deferred.

Milestone 24B1 verifies locally built core artifacts but does not publish them.
Consequently, development deployment still requires the editable core install
shown above. A locally verified wheel is not a public deployment dependency,
and the Home Assistant manifest must not reference it.

After a separately approved 24B2 publication, deployment will install the
exact public core version through the custom-component manifest. That
transition requires a clean public-index installation test first; see the
[release guide](../development/ReleaseGuide.md).
