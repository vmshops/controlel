# Runtime Host Requirements

A deployable host must provide `Scheduler`,
`ScheduledRuntimeFailureSink`, and one serialized execution context for every
`ControlRuntime` entry point. The core does not supply a production scheduler,
thread, task queue, executor, event loop, or Home Assistant adapter.

The host must call `start()` before accepting measurements when silent-sensor
protection is required from startup. It must submit `stop()` through the same
serialized context during shutdown. Direct concurrent stop is rejected rather
than awaited. Stop is terminal, cancels the owned deadline best-effort, and
does not send an implicit heat-source command.

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
