# Runtime Execution Architecture

## Hysteresis and source protection

Temperature strategy output is raw zone demand. A pure, stateful
`TemperatureHysteresisPolicy` converts it to logical demand with asymmetric
enable/disable thresholds, and confirmation establishes each zone's effective
demand independently. `MultiZoneDemandArbitrator` then resolves one immutable
building demand. Safety policy resolves an indeterminate building result.
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

`DemandArbitrator` separates those layers. Milestone 29's
`MultiZoneDemandArbitrator` consumes confirmed `ZoneHeatDemandInput` values and
emits one `BuildingHeatDemand`. Any confirmed heat request wins. If no zone
requests heat, any valid no-heat decision establishes no heat unless an
indeterminate zone carries a previously confirmed active request into the
existing safety/grace layer. All-indeterminate and empty inputs are
indeterminate. Observable zone IDs are sorted by stable `zone_id`.
`SourceControlPolicy` receives only the resolved source command and timing
state; it has no zone ID, temperature, sensor, or Home Assistant dependency.

The building snapshot reports contributing heat zones, valid no-heat zones,
indeterminate zones, counts, and a stable reason code. Aggregation is unweighted:
there are no priorities, percentages, or demand magnitudes. Source configuration
is shared rather than copied into zones because minimum-time protection,
dispatch evidence, deferred commands, and safety belong to the one physical
command path. Milestone 30 heat-delivery coordination is a separate zone-output
concern.

## Zone heat delivery

Milestone 30 adds a separate branch after each zone's confirmation state:

```text
confirmed zone demand -> HeatDeliveryPolicy -> HeatDeliveryCommand
                      -> capability-specific actuator port
```

This branch controls heat delivery into one zone. It cannot change building
aggregation, source minimum-on/off protection, safety, arbitration, or source
water temperature. Zone demand and zone heat delivery are different facts:
zones contribute equally to building demand even when their actuator policies
differ.

The core is vendor independent. `HeatDeliveryCapabilities` represents target
temperature, local/remote temperature, valve-position, binary, HVAC-mode, and
HVAC-action abilities independently. Configuration rejects a control mode when
its required write capability is absent. Stable actuator IDs and ordered
configuration allow multiple actuators per zone; the initial Home Assistant UI
exposes one climate actuator per entry.

- `NATIVE`: a Controlel-owned thermostat target follows the zone target;
  device-owned native actuators receive no writes.
- `SETPOINT_ASSIST`: confirmed heat selects the configured assist target and no
  heat deterministically selects the zone target. This influences the device's
  native control and is neither valve modulation nor a user-requested boost.
- `DIRECT_POSITION`: confirmed heat selects a configured heating position and
  no heat selects a configured idle position. No adaptive algorithm exists.
- `BINARY`: confirmed heat requests open and no heat requests close.

Zone target, trusted zone measurement, and technical actuator target remain
separate. Requested, successfully dispatched, failed, duplicate-suppressed,
commanded, and reported values are also separate. A 100% position command does
not prove that a valve is physically open. Reported state stays unknown unless
a capable adapter supplies it, and a failed command never updates successful
evidence. Actuator failures remain zone-local and recoverable by default rather
than fabricating a fatal source failure.

Remote-temperature forwarding is a distinct optional capability. Only a valid
trusted zone measurement may be forwarded; indeterminate input produces no
invented value. The initial Home Assistant adapter supports generic
`climate.set_temperature` setpoint assist. Configurable direct-position and
binary HA adapters are deferred until safe generic service contracts exist.

Future work includes travel time, acknowledgement, open verification,
last-flow-path safety, and explicit fatal-zone escalation. Milestone 31 may use
current heating-episode facts for adaptive assist and performance observation,
but Milestone 30 adds no learning or persistence. Source-water-temperature
optimization remains a later independent layer.

One scheduler deadline represents the earliest demand-validity, safety-grace,
or deferred-command reevaluation. Expiry always reevaluates current state.
Generation checks reject stale callbacks after rescheduling, reload, or stop.

## Source-control snapshot semantics

The immutable core source-control snapshot owns aggregate demand, logical
machine state, successful enable/disable dispatch evidence, passive
`earliest_next_enable_time` and `earliest_next_disable_time` boundaries,
current active lockout, deferred command metadata, safety-bypass evidence, and
the last requested command/outcome. Home Assistant projects this one snapshot;
entities do not derive competing source state.

A passive boundary records when a future opposite command becomes eligible and
may exist without current demand for that command. An active lockout exists
only when the currently requested command is blocked. A deferred command exists
for exactly the same interval and records reason, start, deadline, and derived
remaining time. Deadline expiry schedules reevaluation of current aggregate
demand and current protection state. It never replays a stored command.

Successful dispatch timestamps prove only that an adapter call returned
successfully. No state name or timestamp claims physical boiler, burner, relay,
or circulation state without explicit future feedback.

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

`ControlRuntime` has no public dynamic zone-addition or zone-removal API.
Configured `ZoneRepository` identity is immutable for one running lifecycle:
duplicate IDs are rejected at repository construction, demand updates replace
state by stable `ZoneId`, and reconfiguration stops the complete old runtime
before constructing a new one. Stop invalidates the owned scheduler generation,
so confirmation callbacks from the removed lifecycle cannot influence the new
aggregate. Per-zone live removal semantics are intentionally deferred until a
serialized configuration-mutation API exists.

## Zone heat-demand confirmation

Milestone 27 inserts a deterministic core policy between zone hysteresis and
the demand-arbitration seam:

```text
measurement -> hysteresis -> zone confirmation -> demand arbitrator
            -> safety -> shared source control
```

The state machine is `no_heat_required`, `confirmation_pending`,
`heat_required_confirmed`, `indeterminate`, `stopped`, or `fatal_error`. State,
start time, and deadline are keyed by stable zone identity; activity in one zone
does not reset another zone's interval or hysteresis memory.
Positive-duration heat demand starts one fresh interval. Repeated identical
measurements retain its start and deadline. At the deadline the serialized
runtime reevaluates current hysteresis demand; it never confirms a stored
request blindly. A no-heat result removes confirmed demand immediately.
Indeterminate input cancels a pending interval, while an already-confirmed
request enters the existing safety/grace policy.

Confirmation is zone-owned. Source minimum on/off policy receives only the
confirmed aggregate demand and remains independent of zone IDs, measurements,
Home Assistant entities, and confirmation state. Restart and reload construct
a fresh policy; pending elapsed time is neither persisted nor inferred from a
physical heat-source state.

## Shadow heating-performance assessment

Completed in-memory heating episodes are submitted after control decisions and
commands are finalized. The Home Assistant host schedules one-shot assessment
drains only after the serialized runtime operation returns; assessment uses the
shared host executor and never holds the runtime execution guard. There is no
polling loop, periodic worker, command path, or feedback into demand, heat
delivery, source control, safety, or scheduling.

Assessment criteria contain explicit deterministic tolerances. Results describe
observed temperature response and evidence quality only. Bounded episode and
pending-assessment history reports truncation or capacity eviction explicitly;
neither is interpreted as physical heat delivery.

Deferred beyond this shadow milestone are failed-assessment retry policy,
persistent history, distinct physical actuator-event accounting, exhaustive
manual evidence-summary consistency validation, physical burner confirmation,
adaptive assistance, and source-water-temperature optimization.

Heating diagnostics follow a one-way boundary:

`Observation -> Assessment -> Diagnostic Projection -> Presentation`

The application projection is immutable, versioned, bounded, and derived only
from existing evidence timestamps. Home Assistant receives this normalized
projection rather than raw episode or assessment objects. Projection and
presentation are never inputs to demand, heat delivery, source control, safety,
or scheduling. Unknown physical actuator and source state remains explicitly
unknown, and reload starts with no inferred diagnostic continuity.
