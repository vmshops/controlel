# Domain Model

## Sensor and zone configuration

`SensorId` is the stable domain identifier of a sensor. `ZoneId` is the stable
domain identifier of a heating zone. Both are immutable value objects; the UUID
provided by `Entity` remains an internal entity identity.

Each configured `Sensor` has exactly one `zone_id`. This field is the single
source of the sensor-to-zone association. `Zone` does not duplicate the
relationship with a sensor list.

A configured `Zone` contains its `ZoneId`, required `primary_sensor_id`, name
and typed `Temperature` target. The primary identifier selects the one sensor
whose accepted measurements may initiate regulation for the zone; it does not
replace or duplicate `Sensor.zone_id` as the sensor-to-zone association.

`Zone` contains no latest measured temperature and no applied heating state.
Those concepts belong to runtime measurement state and control state,
respectively.

Scheduling, disabled-state behavior and configuration mutation are outside the
current domain contract.

## Regulation identity

`SensorId` identifies the observation provenance used to prepare regulation
inputs. `ZoneId` identifies the logical regulated subject. A `ControlContext`
and the resulting `Decision` carry both identifiers so the decision retains
the effective primary sensor's provenance and zone identity.

An executable `Command` carries `ZoneId` as its logical target. It does not
carry `SensorId`, because sensor provenance is not currently execution data.
`ZoneId` is not a physical actuator identifier, and the domain defines no
generic target abstraction.
