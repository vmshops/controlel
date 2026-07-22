from enum import StrEnum


class DecisionAction(StrEnum):
    ENABLE_HEATING = "enable_heating"
    DISABLE_HEATING = "disable_heating"
    OBSERVE_ONLY = "observe_only"
