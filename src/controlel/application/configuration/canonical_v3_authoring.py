"""Authoritative greenfield construction for canonical configuration v3."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field

from controlel.application.configuration.canonical_v3 import (
    DiagnosticsConfigurationV3,
    HeatingConfigurationV3,
    HeatingGlobalConfigurationV3,
    HeatSourceCommandStrategyV3,
    HeatSourceConfigurationV3,
    HeatSourceObservationBindingsV3,
    HeatSourceProtectionPolicyV3,
    NotificationsConfigurationV3,
    PrimaryTemperatureSensorV3,
    ZoneConfigurationV3,
    ZoneDemandPolicyV3,
    ZoneHeatDeliveryConfigurationV3,
    ZoneTopologyV3,
)
from controlel.application.configuration.canonical_v3_lifecycle import ConfigurationScopesV3
from controlel.application.setup.model import ProviderReference

GREENFIELD_ZONE_ID_V3 = "main_zone"
GREENFIELD_PRIMARY_SENSOR_ID_V3 = "primary_temperature_sensor"
GREENFIELD_HEAT_SOURCE_ID_V3 = "main_heat_source"


class GreenfieldHeatingBindingsV3(BaseModel):
    """Explicit provider topology needed to create a new Heating draft.

    Controlel identities are intentionally absent: the authoring boundary owns
    them and never derives them from provider-native IDs or locators.
    """

    zone_display_name: str = Field(min_length=1)
    primary_sensor_display_name: str = Field(min_length=1)
    topology: ZoneTopologyV3
    primary_temperature_sensor_reference: ProviderReference
    heat_source_display_name: str = Field(min_length=1)
    heat_source_reference: ProviderReference | None
    command_strategy: HeatSourceCommandStrategyV3
    observations: HeatSourceObservationBindingsV3

    model_config = ConfigDict(frozen=True, extra="forbid")


def new_configuration_id_v3() -> str:
    """Generate a provider-independent stable Controlel configuration identity."""

    return f"heating_{uuid4().hex}"


def conversion_configuration_id_v3(conversion_key: str) -> str:
    """Generate a deterministic Controlel identity for one explicit conversion."""

    if not conversion_key:
        raise ValueError("conversion key must not be empty")
    return f"heating_{uuid5(NAMESPACE_URL, f'controlel:canonical-v3:{conversion_key}').hex}"


def author_greenfield_heating_scopes_v3(
    bindings: GreenfieldHeatingBindingsV3,
) -> ConfigurationScopesV3:
    """Build new-install scopes using only canonical schema-owned defaults."""

    zone = ZoneConfigurationV3(
        zone_id=GREENFIELD_ZONE_ID_V3,
        display_name=bindings.zone_display_name,
        topology=bindings.topology,
        primary_temperature_sensor=PrimaryTemperatureSensorV3(
            sensor_id=GREENFIELD_PRIMARY_SENSOR_ID_V3,
            display_name=bindings.primary_sensor_display_name,
            provider_reference=bindings.primary_temperature_sensor_reference,
        ),
        demand_policy=ZoneDemandPolicyV3(),
    )
    source = HeatSourceConfigurationV3(
        heat_source_id=GREENFIELD_HEAT_SOURCE_ID_V3,
        display_name=bindings.heat_source_display_name,
        provider_reference=bindings.heat_source_reference,
        command_strategy=bindings.command_strategy,
        observations=bindings.observations,
        protection=HeatSourceProtectionPolicyV3(),
    )
    return ConfigurationScopesV3(
        heating=HeatingConfigurationV3.model_validate(
            {
                "global": HeatingGlobalConfigurationV3(),
                "zones": (zone,),
                "heat_sources": (source,),
                "heat_delivery": (ZoneHeatDeliveryConfigurationV3(zone_id=zone.zone_id),),
            }
        ),
        diagnostics=DiagnosticsConfigurationV3(),
        notifications=NotificationsConfigurationV3(),
    )
