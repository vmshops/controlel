# Control Flow

The synchronous in-memory runtime flow is:

```text
Measurement
-> TemperatureMeasuredEvent
-> RuntimeStateStore
-> SensorRepository
-> Sensor.zone_id
-> ZoneRepository
-> Zone(zone_id, primary_sensor_id, primary_measurement_max_age, target_temperature)
-> ZoneTemperatureAggregator
-> Clock.now()
-> latest primary Measurement | None
-> ControlContext(sensor_id, zone_id)
-> Regulation
-> Decision(sensor_id, zone_id)
-> DecisionCreatedEvent
-> DecisionEventHandler
-> Command(zone_id) | None
-> CommandDispatcher
-> StateRepository lookup by ZoneId
-> suppress identical applied action | ActuatorPort
-> StateRepository update after success
```

`ControlRuntime` explicitly invokes each functional handler. It processes a
temperature event through `TemperatureEventHandler` before publishing that
event to observers. A stale measurement produces no decision or command, but
its temperature event is still published.

For an accepted measurement, `TemperatureEventHandler` resolves the target
from explicit zone configuration using the measurement's typed `SensorId`.
Missing sensor or zone configuration raises without a fallback. The accepted
measurement remains recorded, functional processing stops before a decision,
and the temperature event is not published because functional handling occurs
before observer notification.

The handler then validates the zone's configured primary sensor and retrieves
its exact latest measurement from runtime state. Only an accepted incoming
measurement from that primary sensor creates `ControlContext`. An accepted
secondary measurement remains stored and is subsequently published as a
temperature event, but produces no decision event or command—even when primary
state already exists. Missing primary state also produces no decision.

The aggregator reads the injected application `Clock` exactly once. A primary
measurement is eligible when its timestamp is between
`now - Zone.primary_measurement_max_age` and `now`, inclusive. An expired or
future-dated primary observation remains in runtime state and is published to
observers, but produces no context, decision, command or applied-state update.
A missing primary observation returns no effective measurement. Invalid
primary configuration still raises its explicit exception.

`SystemClock` is the UTC infrastructure implementation; `ControlRuntime`
requires a `Clock` explicitly and does not construct one. This keeps freshness
tests deterministic and prevents direct wall-clock access in application
aggregation and handling.

Same-sensor out-of-order rejection remains separate and happens before
configuration and freshness evaluation. No cross-sensor timestamps are
compared. A stored future observation may therefore block later
lower-timestamp inputs under the unchanged state-store ordering contract.

There is no fallback sensor, arithmetic or weighted aggregation, clock-skew
tolerance, timestamp-admission policy, cleanup, timer or health monitor.
Freshness is checked only when aggregation is invoked; a sensor that silently
stops reporting causes no timed reaction. Expiry emits no fail-safe command and
does not change previously applied control state.

Functional handlers are not subscribed by `ControlRuntime`. `EventBus` is
notification-only: it calls observers synchronously in registration order,
discards their return values and returns `None`. Observer return values cannot
change the functional result.

`Decision` remains a description of the regulation result. The application
handler explicitly maps `enable_heating` and `disable_heating` to commands in
the `heating` command family. Other actions produce no command.

`SensorId` is carried from the measurement through `ControlContext` into the
decision as observation provenance. The configured `ZoneId` is carried through
the same models as the logical regulated subject. `DecisionCreatedEvent`
contains the complete decision and does not duplicate either identifier.

Supported commands copy `Decision.zone_id` as their logical execution target.
They do not copy `SensorId`, reason, metadata or timestamp because those values
are not currently required for execution. Future durable causal tracing should
use explicit correlation or causation identity rather than overload
`SensorId`.

`EventBus` publishes `DecisionCreatedEvent` for notification before runtime
explicitly invokes command mapping. Decision publication is not a
request/response operation.

`CommandDispatcher` compares a command with the latest successfully applied
action for its `ZoneId`. An identical action is suppressed without actuator
execution or state mutation. A different action executes through the injected
`ActuatorPort`, then becomes the new immutable `ControlState` only after normal
return. Execution exceptions propagate unchanged and preserve the previous
state, so a later measurement may retry the action.

Suppression does not remove the regulation result: repeated accepted primary
measurements may still produce and publish decisions, create commands and
return `DecisionCreatedEvent`. Only redundant actuator execution is skipped.

The current flow has no command routing, retry policy, persistence, physical
feedback or concurrency protection. A normal adapter return records logical
application-level success but does not confirm physical hardware state.

`ZoneId` is not a physical actuator identifier. Commands targeted to different
zones still pass through the same injected `ActuatorPort`; zone-to-actuator
routing is intentionally absent. Multiple sensors associated with one zone may
currently produce repeated or conflicting commands.

Observers may delay runtime processing, and observer exceptions currently
propagate to the caller. Observer isolation and concurrency are outside the
current design.

Scheduling, disabled-state behavior, configuration persistence and mutation,
and zone-based actuator routing are also outside the current flow.
