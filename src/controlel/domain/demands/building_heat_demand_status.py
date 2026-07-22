from enum import StrEnum


class BuildingHeatDemandStatus(StrEnum):
    HEAT_REQUIRED = "heat_required"
    NO_HEAT_REQUIRED = "no_heat_required"
    INDETERMINATE = "indeterminate"
