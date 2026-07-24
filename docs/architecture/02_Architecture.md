# Runtime Execution Architecture

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
`start()` remains a repeatable safety evaluation. `stop()` transitions
terminally to `STOPPED`; restart requires a new runtime instance. Shutdown
invalidates timer generation and clears timer ownership before best-effort
cancellation. It issues no heat-source command.

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
