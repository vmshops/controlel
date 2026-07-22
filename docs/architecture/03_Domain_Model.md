# Domain Model

## Sensor and zone configuration

`SensorId` is the stable domain identifier of a sensor. `ZoneId` is the stable
domain identifier of a heating zone. Both are immutable value objects; the UUID
provided by `Entity` remains an internal entity identity.

Each configured `Sensor` has exactly one `zone_id`. This field is the single
source of the sensor-to-zone association. `Zone` does not duplicate the
relationship with a sensor list.

A configured `Zone` contains its `ZoneId`, required `primary_sensor_id`,
strictly positive `primary_measurement_max_age`, name and typed `Temperature`
target. The maximum age is a required `timedelta` with no default and defines
the inclusive freshness boundary for the primary observation. The primary
identifier selects the one sensor whose accepted measurements may initiate
regulation for the zone; it does not replace or duplicate `Sensor.zone_id` as
the sensor-to-zone association.

`Zone` contains no latest measured temperature and no applied heating state.
Those concepts belong to runtime measurement state and control state,
respectively.

Scheduling, disabled-state behavior and configuration mutation are outside the
current domain contract.

Freshness is evaluated by the application against an injected clock. It does
not change `Measurement`, delete runtime observations, or add sensor health or
fallback behavior to the domain model.

## Regulation identity

`SensorId` identifies the observation provenance used to prepare regulation
inputs. `ZoneId` identifies the logical regulated subject. A `ControlContext`
and the resulting `Decision` carry both identifiers so the decision retains
the effective primary sensor's provenance and zone identity.

An executable `Command` carries `ZoneId` as its logical target. It does not
carry `SensorId`, because sensor provenance is not currently execution data.
`ZoneId` is not a physical actuator identifier, and the domain defines no
generic target abstraction.

At runtime, the application-layer `ZoneActuatorRouter` maps each configured
`ZoneId` directly to exactly one `ActuatorPort`. A port may serve multiple
zones, but a zone does not fan out to multiple ports. The router copies its
runtime configuration and exposes no mutation or default route. This adds no
`ActuatorId`, actuator registry, persistence, discovery, physical topology or
family-based routing to the domain model.

## Heating decision and command vocabulary

`DecisionAction` is the typed regulation vocabulary. Its stable serialized
values are `enable_heating`, `disable_heating` and `observe_only`.
`OBSERVE_ONLY` is an intentional decision that creates no executable request.

`HeatingAction` is the separate executable heating vocabulary and contains
only `enable_heating` and `disable_heating`. `CommandFamily` currently contains
only the stable `heating` family. A `Decision` therefore carries a
`DecisionAction`, while a `Command` carries both a `CommandFamily` in its
existing `command_type` field and a `HeatingAction`.

The types are deliberately separate: regulation describes an outcome, while
a command requests execution. Unknown values and misspellings fail model
validation, and there are no aliases, generic action registry, routing model,
physical target taxonomy or plugin action system. Python-mode model data
retains enum instances; JSON serialization exposes the stable string values.
Future vocabulary additions require a deliberate mapping update.

## Applied control state

`ControlState` is the latest successfully applied logical action for one
`ZoneId`. It records the exact `HeatingAction`, the successful command identity
and the application-level execution time. It contains no measurement or target
configuration.

Applied state is distinct from a `Decision`, which describes what regulation
wants, and from a `Command`, which is an executable request that may still fail
or be suppressed.

Actuator routing is resolved before applied-state suppression. Applied state
remains keyed by logical `ZoneId`; it does not identify a physical actuator or
store routing configuration.
