# Event Model

## Notification contract

`EventBus` is a synchronous observer-notification mechanism. It notifies every
matching subscriber in registration order, discards subscriber return values
and always returns `None`. Dictionary event keys and class-based event keys are
both supported.

Functional handlers are invoked explicitly by `ControlRuntime`; they are not
also subscribed by the runtime. This avoids duplicate execution and prevents
functional results from depending on subscriber ordering.

Temperature measurement processing occurs before `TemperatureMeasuredEvent`
is published. Observers therefore cannot alter the event before runtime state
and regulation have processed it. Rejected stale measurement events are still
published and remain observable. Measurements beyond the configured future
admission boundary are also published, but are not stored and produce no
control context, decision or command. Observers cannot currently distinguish
the exact no-decision reason from event fields alone.

Admitted primary measurements that are expired or still future-dated at
aggregation time are stored and published, but likewise produce no control
context, decision or command. No admission-rejection event is emitted.

Accepted measurements from secondary zone sensors are also published and
remain observable after being stored, but they produce no `ControlContext`,
decision event or command. A zone with no latest primary measurement likewise
produces no decision.

Elapsed-time expiry creates no expiration or health event. Evaluation occurs
only when aggregation is invoked; there is no timer that publishes an event
when a sensor silently stops reporting.

Subscribers run synchronously and may delay runtime processing. Subscriber
exceptions currently propagate unchanged.

## Synchronous processing outcome

Events remain notification-only and unchanged. Independently of publication,
`ControlRuntime.process_temperature()` returns an immutable
`RuntimeProcessingResult` for every normally completed invocation. Its stable
`RuntimeProcessingStatus` codes distinguish `no_decision`,
`decision_without_command`, `command_executed` and `command_suppressed`.

A `no_decision` result includes one stable `TemperatureNoDecisionReason` code:
`timestamp_admission_rejected`, `out_of_order`, `secondary_measurement`,
`primary_measurement_missing`, `primary_measurement_expired` or
`primary_measurement_future_dated`. Expected no-action paths are results, not
exceptions.

The result references the existing `DecisionCreatedEvent` and `Command` when
present; it does not copy their fields. Result objects exist only when
processing completes normally. Configuration, routing, clock, observer,
actuator, validation and unexpected failures remain exceptions, so no
misleading result is returned when they interrupt processing.

Event-only observers do not receive the synchronous runtime result. No
diagnostic events, logging, persistence or correlation identifiers are
introduced.

## Decision notifications

Regulation produces a `Decision`, which describes what the regulation logic
decided and why. `ControlLoopService` wraps that result in a
`DecisionCreatedEvent`.

`ControlRuntime` publishes the event through `EventBus` so notification
subscribers can observe decisions. Decision events are notifications, not
request/response calls. After publication, the runtime explicitly passes the
event to `DecisionEventHandler`.

The contained `Decision` is the authoritative source of its `SensorId`
observation provenance and `ZoneId` regulated-subject identity.
`DecisionCreatedEvent` does not duplicate those identifiers as event fields.

Decision notification remains independent of command execution. A decision
event is still published when its mapped command is later suppressed because
the same zone action is already applied, and it is published before an
actuator route is resolved or execution is attempted. A missing route therefore
propagates `ActuatorRouteNotFoundError` after decision publication, without a
runtime result or applied-state change. The caller receives
`command_suppressed` or `command_executed` only after dispatch completes
normally.

The handler is the explicit typed mapping boundary. It maps
`DecisionAction.ENABLE_HEATING` to `HeatingAction.ENABLE_HEATING` and
`DecisionAction.DISABLE_HEATING` to `HeatingAction.DISABLE_HEATING`, always in
`CommandFamily.HEATING`. `DecisionAction.OBSERVE_ONLY` is the sole intentional
decision-without-command outcome and returns `None` without reaching the
actuator boundary. The mapping is exhaustive, so a future decision action must
receive deliberately designed command behavior rather than silently becoming
a no-command outcome.

Decision and command actions intentionally use different string-backed enum
types. Their JSON values remain stable, while Python-mode data retains enum
instances. Unknown values and misspellings fail validation; no compatibility
aliases or generic action registry exist.

A `Command` is an explicit request, not an event describing something that
already happened. No command-created event is introduced in the current flow.
Commands carry the decision's `ZoneId` as a logical execution target but do not
carry `SensorId`.

`ZoneActuatorRouter` is application runtime composition, not event processing.
It maps `Command.zone_id` directly to one configured `ActuatorPort`, has no
default, and distinguishes missing routing configuration from exceptions raised
by a resolved port during execution.
