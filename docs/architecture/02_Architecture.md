# Runtime Execution Architecture

## Serialized host boundary

The future runtime host or host event loop is the authoritative owner of
serialized `ControlRuntime` execution. It must submit `start()`,
`process_temperature()`, `reevaluate_heat_demand()`, scheduled callbacks, and
`stop()` through one context. `ControlRuntime` does not create a queue,
executor, worker, thread, or event loop.

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
`start()` remains a repeatable safety evaluation. `stop()` transitions
terminally to `STOPPED`; restart requires a new runtime instance. Shutdown
invalidates timer generation and clears timer ownership before best-effort
cancellation. It issues no heat-source command.

The host must provide:

- the `Scheduler` application port;
- the mandatory `ScheduledRuntimeFailureSink`;
- serialized submission of every runtime entry point;
- future wall-clock-to-monotonic deadline conversion when appropriate.

There is no production Scheduler or Home Assistant integration in the core.
