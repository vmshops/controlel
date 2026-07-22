# Domain Model

## Sensor and zone configuration

`SensorId` is the stable domain identifier of a sensor. `ZoneId` is the stable
domain identifier of a heating zone. Both are immutable value objects; the UUID
provided by `Entity` remains an internal entity identity.

Each configured `Sensor` has exactly one `zone_id`. This field is the single
source of the sensor-to-zone association. `Zone` does not duplicate the
relationship with a sensor list.

A configured `Zone` contains its `ZoneId`, name, enabled state and a typed
`Temperature` target. It contains no latest measured temperature and no
applied heating state. Those concepts belong to runtime measurement state and
control state, respectively.

Scheduling, disabled-state behavior and configuration mutation are outside the
current domain contract.
