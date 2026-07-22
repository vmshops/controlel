# State Model

## Latest measurement state

`RuntimeStateStore` remains the application-layer latest-observation store. It
holds at most one admitted `Measurement` per `SensorId`; equal timestamps use
arrival order and older same-sensor input is rejected. Historical measurements
remain a separate future concern.

Timestamp admission still occurs before storage using the required injected
`Clock` and runtime-wide `max_future_skew`. Primary measurement eligibility is
still:

```text
now - Zone.primary_measurement_max_age <= Measurement.timestamp <= now
```

Missing, expired, or future-dated primary observations create no decision.
They are not removed, and no fallback sensor or fail-safe action is introduced.

## Requested zone-demand state

`ZoneDemandStore` is separate in-memory desired state. It retains at most one
immutable `ZoneDemand` per `ZoneId`, preserves first-zone insertion order, and
exposes list snapshots. A new actionable decision replaces only its zone's
demand. The store does not evaluate freshness or remove expired entries.

Admission rejection, out-of-order input, secondary input, missing or ineligible
primary observations, configuration exceptions, and `OBSERVE_ONLY` do not
change retained zone demand.

Demand freshness uses `ZoneDemand.observed_at`, which is the exact originating
measurement timestamp. It never uses `Decision.timestamp`. During each
arbitration, `HeatDemandAggregator` reads `Clock.now()` once and classifies every
configured zone:

```text
missing demand                         -> unknown
observed_at < now - primary max age   -> expired / unknown
observed_at > now                     -> future-dated / unknown
cutoff <= observed_at <= now          -> eligible
```

Expired demands remain stored for diagnostics. A source-sensor mismatch raises
an explicit configuration/state exception rather than becoming unknown.

## Building heat demand

Every zone in `ZoneRepository` participates, regardless of inherited
`Entity.enabled`. The tri-state truth table is:

| Evidence | Status |
|---|---|
| No configured zones | `INDETERMINATE` |
| Any eligible true demand | `HEAT_REQUIRED` |
| Every configured zone has eligible false demand | `NO_HEAT_REQUIRED` |
| Anything else | `INDETERMINATE` |

Missing, expired, and future demand is unknown, never implicit false. Thus an
eligible true overrides uncertainty, while disabling requires complete fresh
false evidence.

## Applied shared-source state

`HeatSourceStateStore` holds one latest immutable `HeatSourceControlState`.
`HeatSourceCommandDispatcher` suppresses an action only when the same action was
already successfully applied. It saves new state only after
`HeatSourcePort.execute()` returns normally.

If execution raises, updated requested demands remain stored, prior applied
source state is preserved, and the exact exception propagates. A later
actionable decision re-runs arbitration and can retry because failed execution
was never recorded. There is no internal or scheduled retry.

The existing per-zone `ControlState` and `StateRepository` remain the separate
zone-actuator applied-state model and are not reused for the shared source.

All runtime, demand, and applied-source state is lost on restart. With no
retained demands there is no implicit source action; arbitration begins only
after a new actionable decision. Normal port return records application-level
success, not physical boiler confirmation.
