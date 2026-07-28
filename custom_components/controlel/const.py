"""Constants for the Controlel Home Assistant integration."""

DOMAIN = "controlel"
INTEGRATION_VERSION = "0.3.0"
CONFIG_ENTRY_VERSION = 1

CONTROL_MODE_SIMPLE = "simple_switch"
CONTROL_MODE_CUSTOM = "custom_services"

CONF_SENSOR_ID = "sensor_id"
CONF_SENSOR_NAME = "sensor_name"
CONF_TEMPERATURE_ENTITY_ID = "temperature_entity_id"
CONF_ZONE_ID = "zone_id"
CONF_ZONE_NAME = "zone_name"
CONF_TARGET_TEMPERATURE = "target_temperature"
CONF_HEAT_SOURCE_CONTROL_MODE = "heat_source_control_mode"
CONF_CONTROLLED_ENTITY_ID = "controlled_entity_id"
CONF_SHOW_ADVANCED = "show_advanced"
CONF_PRIMARY_MEASUREMENT_MAX_AGE_MINUTES = "primary_measurement_max_age_minutes"
CONF_PRIMARY_MEASUREMENT_MAX_AGE = "primary_measurement_max_age"
CONF_MAX_FUTURE_SKEW = "max_future_skew"
CONF_INDETERMINATE_GRACE_PERIOD_MINUTES = "indeterminate_grace_period_minutes"
CONF_INDETERMINATE_GRACE_PERIOD = "indeterminate_grace_period"
CONF_INDETERMINATE_TIMEOUT_ACTION = "indeterminate_timeout_action"
CONF_ENABLE_SERVICE_DOMAIN = "enable_service_domain"
CONF_ENABLE_SERVICE_NAME = "enable_service_name"
CONF_ENABLE_TARGET_ENTITY_ID = "enable_target_entity_id"
CONF_DISABLE_SERVICE_DOMAIN = "disable_service_domain"
CONF_DISABLE_SERVICE_NAME = "disable_service_name"
CONF_DISABLE_TARGET_ENTITY_ID = "disable_target_entity_id"

DEFAULT_TARGET_TEMPERATURE = 21.0
DEFAULT_PRIMARY_MEASUREMENT_MAX_AGE = 900.0
DEFAULT_MAX_FUTURE_SKEW = 30.0
DEFAULT_INDETERMINATE_GRACE_PERIOD = 120.0
DEFAULT_INDETERMINATE_TIMEOUT_ACTION = "disable_heating"

ATTR_UNIT_OF_MEASUREMENT = "unit_of_measurement"
ATTR_DEVICE_CLASS = "device_class"
STATE_UNKNOWN = "unknown"
STATE_UNAVAILABLE = "unavailable"
UNIT_CELSIUS = "°C"
UNIT_FAHRENHEIT = "°F"

RECOVERABLE_SERVICE_ISSUE_SUFFIX = "heat_source_service_failure"
FATAL_RUNTIME_ISSUE_SUFFIX = "fatal_runtime_failure"
