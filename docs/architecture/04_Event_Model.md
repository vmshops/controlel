# Event Model

## Notification contract

`EventBus` remains a synchronous notification mechanism. It calls subscribers
in registration order, discards return values, and returns `None`. Functional
handlers are invoked explicitly by `ControlRuntime`, not subscribed to the
bus. Subscriber exceptions propagate unchanged.

Temperature handling occurs before `TemperatureMeasuredEvent` publication.
Every normal handler result publishes its exact temperature event, including
admission rejection, ordering rejection, secondary input, and ineligible
primary observations. A configuration exception interrupts processing before
normal notification, as before.

Every produced `DecisionCreatedEvent` is published before demand creation,
arbitration, or shared-source execution. The event contains the complete
`Decision`, including `SensorId`, `ZoneId`, and `observed_at`; it does not
duplicate those fields.

The event bus does not return decisions, demands, aggregates, commands, or
runtime results. No demand, aggregate, command-created, expiration, diagnostic,
or health event is introduced.

## Decision notification and execution separation

`DecisionAction` now explicitly represents zone heating-demand intent. After
decision publication, `ZoneDemandHandler` maps enable and disable intent to a
retained `ZoneDemand`; `OBSERVE_ONLY` maps to no demand and leaves existing
demand unchanged.

The shared-source runtime then derives `BuildingHeatDemand`. A determinate
aggregate creates `HeatSourceCommand`; indeterminate demand creates no command.
Source execution is therefore explicit orchestration and never depends on
event subscriber ordering or return values.

The existing `DecisionEventHandler` still maps decisions to zone-targeted
`Command` objects for the independent zone-actuator path. `ControlRuntime` does
not invoke that path for the shared source.

Decision publication remains observable even when source execution is later
suppressed or fails. If a decision observer raises, demand is not updated and
source processing does not begin. No result object is returned for observer,
configuration, clock, validation, or port exceptions.

## Synchronous processing result

`RuntimeProcessingResult` retains the existing stable statuses and adds
`building_heat_demand_indeterminate`. No-decision results retain their existing
typed reasons. Indeterminate results carry the exact decision event and
aggregate but no command. Executed and suppressed results carry the exact
decision event, determinate aggregate, and `HeatSourceCommand`.

Event-only observers do not receive this synchronous result. Logging,
persistence, correlation IDs, and diagnostic events remain outside scope.
