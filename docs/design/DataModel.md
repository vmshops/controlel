# Controlel Data Model

Version:
0.1

Status:
Draft


# 1. Purpose


# 2. Core Entities


# 3. Entity Relationships


# 4. Configuration Model

Configuration supplies target values and other regulation inputs. Target
temperature is not an observed measurement and is not stored in runtime
measurement state.

# 5. Runtime Model

The application maintains one latest `Measurement` per stable `SensorId` in an
in-memory `RuntimeStateStore`. Measurements contain only the sensor identity,
observed temperature and timezone-aware observation timestamp.

Runtime measurement state is used to prepare `ControlContext`. It is separate
from control state, which describes regulation or actuator condition.

# 6. Historical Data Model

Historical measurements are not part of the runtime store. A future history
model may append observations and persist them, but the current runtime model
only retains the latest accepted measurement for each sensor.
