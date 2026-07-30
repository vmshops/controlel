# Runtime Execution Architecture

## Hysteresis and source protection

Temperature strategy output is raw zone demand. A pure, stateful
`TemperatureHysteresisPolicy` converts it to logical demand with asymmetric
enable/disable thresholds. Safety policy then resolves indeterminate demand.
Finally, `SourceControlPolicy` arbitrates the requested heat-source command
against command-dispatch-based minimum on/off deadlines. Home Assistant owns
configuration, serialized execution, scheduling adapters, and observation, not
these deterministic rules.

The ownership boundary is explicit:

- zone control owns target temperature, turn-on and turn-off differentials,
  raw measurement state, hysteresis demand, and future valve/priority policy;
- shared heat-source control owns minimum on/off time, dispatch history,
  lockout deadlines, deferred source commands, anti-cycling state, safety
  bypass, and future water/return-temperature, modulation, and source
  diagnostics.

`DemandArbitrator` separates those layers. The current
`IdentityDemandArbitrator` maps the already-aggregated one-zone demand directly
to shared-source demand. It deliberately contains no future multi-zone rules.
`SourceControlPolicy` receives only the resolved source command and timing
state; it has no zone ID, temperature, sensor, or Home Assistant dependency.

One scheduler deadline represents the earliest demand-validity, safety-grace,
or deferred-command reevaluation. Expiry always reevaluates current state.
Generation checks reject stale callbacks after rescheduling, reload, or stop.

## Integration observability controller

The integration owns presentation policy separately from the core runtime.
One `ObservabilityController` per config entry selects Basic event-driven,
Detailed 10-second, or Debug one-second cadence and 20/100/500-record trace
capacity. It schedules only while at least one supported countdown is active,
updates only elapsed/countdown subscribers on ticks, and uses cancellation plus
generation checks to reject callbacks after reschedule, reload, unload, stop,
replacement, fatal transition, or Debug expiry.

Profiles never feed back into measurement admission, hysteresis, safety,
demand arbitration, source-control policy, or command dispatch. The operational
summary is selected from stable machine states and describes only demand,
safety, lockout/deferred action, requested command, and dispatch outcome. It
never represents an unobserved physical heat-source state.

## Serialized host boundary

The Home Assistant runtime host is the first authoritative owner of serialized
`ControlRuntime` execution. It submits `start()`,
`process_temperature()`, `reevaluate_heat_demand()`, scheduled callbacks, and
`stop()` through one dedicated `ThreadPoolExecutor(max_workers=1)`.
`ControlRuntime` itself still creates no queue, executor, worker, thread, or
event loop.

The runtime defensively holds one non-reentrant execution guard across each
complete state transition, including event observers, scheduler calls, and
`HeatSourcePort.execute()`. Acquisition never waits. Overlap or synchronous
re-entry raises `RuntimeReentrancyError` immediately; a compliant host should
not encounter that exception during routine execution.

Runtime-owned stores are accessed only under this guard. Sensor and zone
configuration must not change concurrently with operation. Event subscribers
must be configured before processing or through the same host context. Ports
must not mutate runtime-owned state independently.

## Lifecycle and integration responsibilities

Construction is side-effect free and begins in private `OPEN` state.
`start()` remains a repeatable safety evaluation. Normal `stop()` transitions
terminally to `STOPPED`; restart requires a new runtime instance. Normal
shutdown invalidates timer generation and clears timer ownership before
best-effort cancellation. It issues no heat-source command.

Fatal shutdown is a separate terminal path. It first invalidates callbacks and
clears deferred/lockout state, then makes at most one best-effort emergency
`disable_heating` request outside normal duplicate suppression and minimum-time
policy. A fatal failure already caused by `disable_heating` skips that request
to prevent recursion. Emergency dispatch is recorded only as a request
outcome, never as confirmed physical source state, and never starts a normal
minimum-off timer or automatic retry.

The host must provide:

- the `Scheduler` application port;
- the mandatory `ScheduledRuntimeFailureSink`;
- serialized submission of every runtime entry point;
- future wall-clock-to-monotonic deadline conversion when appropriate.

The deployable adapter lives in `custom_components/controlel` and imports the
core. Domain and application modules never import Home Assistant or adapter
code. One typed `ConfigEntry.runtime_data` container owns one
`HomeAssistantControlelHost`; no runtime host is stored in `hass.data`.

Home Assistant event callbacks only buffer or submit work. A narrowly scoped
thread-safe bridge lets the runtime worker request timer installation,
cancellation, and blocking service completion on the Home Assistant event
loop. Bridge coroutines never acquire the host's submission/lifecycle lock.

The initial adapter is deliberately one entry, one zone, one primary sensor,
and one shared heat source. Reconfiguration unloads and reconstructs the
runtime; repositories are never mutated live.
