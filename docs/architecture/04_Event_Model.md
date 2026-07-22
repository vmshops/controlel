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
actuator execution that may fail.

The handler maps supported decision actions to an executable `Command`. A
decision may produce no command. Unsupported or non-actionable actions return
`None` and do not reach the actuator boundary.

A `Command` is an explicit request, not an event describing something that
already happened. No command-created event is introduced in the current flow.
Commands carry the decision's `ZoneId` as a logical execution target but do not
carry `SensorId`.
