from datetime import UTC, datetime

import pytest

from controlel.application.services.zone_heat_delivery_controller import ZoneHeatDeliveryController
from controlel.domain.demands.building_heat_demand_status import BuildingHeatDemandStatus
from controlel.domain.heat_delivery import (
    HeatDeliveryActuatorConfiguration,
    HeatDeliveryActuatorId,
    HeatDeliveryAssistPolicy,
    HeatDeliveryCapabilities,
    HeatDeliveryCommandKind,
    HeatDeliveryCommandOutcome,
    HeatDeliveryMode,
    HeatDeliveryOwnership,
)
from controlel.domain.value_objects.zone_id import ZoneId

NOW = datetime(2026, 1, 1, tzinfo=UTC)
ZONE_A = ZoneId("zone_a")
ZONE_B = ZoneId("zone_b")


class RecordingPort:
    def __init__(self, *, fail: bool = False) -> None:
        self.commands = []
        self.fail = fail

    def execute(self, command) -> None:
        self.commands.append(command)
        if self.fail:
            raise RuntimeError("service unavailable")


def configuration(
    actuator: str = "actuator_a",
    *,
    zone_id: ZoneId = ZONE_A,
    mode: HeatDeliveryMode = HeatDeliveryMode.SETPOINT_ASSIST,
    ownership: HeatDeliveryOwnership = HeatDeliveryOwnership.CONTROLEL_OWNED,
    capabilities: HeatDeliveryCapabilities | None = None,
    forward_remote_temperature: bool = False,
) -> HeatDeliveryActuatorConfiguration:
    capabilities = capabilities or HeatDeliveryCapabilities(can_set_target_temperature=True)
    return HeatDeliveryActuatorConfiguration(
        actuator_id=HeatDeliveryActuatorId(actuator),
        zone_id=zone_id,
        capabilities=capabilities,
        mode=mode,
        ownership=ownership,
        assist_policy=HeatDeliveryAssistPolicy.ALWAYS_ASSIST_WHILE_HEATING,
        assist_target_temperature=30.0,
        heating_position=100.0 if mode is HeatDeliveryMode.DIRECT_POSITION else None,
        idle_position=0.0 if mode is HeatDeliveryMode.DIRECT_POSITION else None,
        forward_remote_temperature=forward_remote_temperature,
    )


def evaluate(
    controller: ZoneHeatDeliveryController,
    demand: BuildingHeatDemandStatus,
    *,
    zone_id: ZoneId = ZONE_A,
    target: float = 22.0,
    measurement: float | None = 20.0,
):
    return controller.evaluate_zone(
        zone_id=zone_id,
        confirmed_demand=demand,
        zone_target_temperature=target,
        valid_zone_measurement_temperature=measurement,
        now=NOW,
    )


def test_setpoint_assist_dispatches_once_then_restores_normal_target_once() -> None:
    config = configuration()
    port = RecordingPort()
    controller = ZoneHeatDeliveryController((config,), {config.actuator_id: port})

    evaluate(controller, BuildingHeatDemandStatus.HEAT_REQUIRED)
    evaluate(controller, BuildingHeatDemandStatus.HEAT_REQUIRED)
    assert [command.value for command in port.commands] == [30.0]
    assert controller.states[0].last_command_outcome is HeatDeliveryCommandOutcome.SUPPRESSED_DUPLICATE

    evaluate(controller, BuildingHeatDemandStatus.NO_HEAT_REQUIRED)
    evaluate(controller, BuildingHeatDemandStatus.NO_HEAT_REQUIRED)
    assert [command.value for command in port.commands] == [30.0, 22.0]
    assert controller.states[0].commanded_target_temperature == 22.0
    assert controller.states[0].assist_active is False


def test_native_ownership_and_changed_zone_target_are_deterministic() -> None:
    owned = configuration(mode=HeatDeliveryMode.NATIVE)
    port = RecordingPort()
    controller = ZoneHeatDeliveryController((owned,), {owned.actuator_id: port})
    evaluate(controller, BuildingHeatDemandStatus.HEAT_REQUIRED)
    evaluate(controller, BuildingHeatDemandStatus.NO_HEAT_REQUIRED, target=23.0)
    assert [command.value for command in port.commands] == [22.0, 23.0]

    observed = configuration(
        "observed",
        mode=HeatDeliveryMode.NATIVE,
        ownership=HeatDeliveryOwnership.DEVICE_OWNED,
        capabilities=HeatDeliveryCapabilities(can_read_target_temperature=True),
    )
    observed_port = RecordingPort()
    observed_controller = ZoneHeatDeliveryController((observed,), {observed.actuator_id: observed_port})
    evaluate(observed_controller, BuildingHeatDemandStatus.HEAT_REQUIRED)
    assert observed_port.commands == []


def test_failed_write_never_becomes_successful_or_duplicate_evidence() -> None:
    config = configuration()
    port = RecordingPort(fail=True)
    controller = ZoneHeatDeliveryController((config,), {config.actuator_id: port})
    evaluate(controller, BuildingHeatDemandStatus.HEAT_REQUIRED)
    evaluate(controller, BuildingHeatDemandStatus.HEAT_REQUIRED)
    state = controller.states[0]
    assert len(port.commands) == 2
    assert state.last_successful_command is None
    assert state.commanded_target_temperature is None
    assert state.last_command_outcome is HeatDeliveryCommandOutcome.FAILED
    assert state.actuator_failure_active is True


def test_reload_reconstructs_target_without_remembering_device_value() -> None:
    config = configuration()
    first = RecordingPort()
    evaluate(ZoneHeatDeliveryController((config,), {config.actuator_id: first}), BuildingHeatDemandStatus.HEAT_REQUIRED)
    reloaded = RecordingPort()
    evaluate(
        ZoneHeatDeliveryController((config,), {config.actuator_id: reloaded}), BuildingHeatDemandStatus.HEAT_REQUIRED
    )
    assert [command.value for command in reloaded.commands] == [30.0]


def test_direct_position_and_binary_commands_are_explicit_and_truthful() -> None:
    direct = configuration(
        mode=HeatDeliveryMode.DIRECT_POSITION,
        capabilities=HeatDeliveryCapabilities(can_write_valve_position=True),
    )
    binary = configuration(
        "binary",
        mode=HeatDeliveryMode.BINARY,
        capabilities=HeatDeliveryCapabilities(can_open_close_binary=True),
    )
    direct_port, binary_port = RecordingPort(), RecordingPort()
    controller = ZoneHeatDeliveryController(
        (binary, direct),
        {direct.actuator_id: direct_port, binary.actuator_id: binary_port},
    )
    evaluate(controller, BuildingHeatDemandStatus.HEAT_REQUIRED)
    assert direct_port.commands[0].kind is HeatDeliveryCommandKind.SET_POSITION
    assert direct_port.commands[0].value == 100.0
    assert binary_port.commands[0].kind is HeatDeliveryCommandKind.SET_BINARY_OPEN
    assert binary_port.commands[0].value is True
    states = {state.actuator_id.value: state for state in controller.states}
    assert states["actuator_a"].commanded_position == 100.0
    assert states["actuator_a"].reported_position is None


def test_capability_mismatch_is_rejected_at_configuration_boundary() -> None:
    with pytest.raises(ValueError, match="target-temperature write capability"):
        configuration(capabilities=HeatDeliveryCapabilities())
    with pytest.raises(ValueError, match="valve-position write capability"):
        configuration(mode=HeatDeliveryMode.DIRECT_POSITION, capabilities=HeatDeliveryCapabilities())


def test_valid_remote_temperature_is_forwarded_but_indeterminate_is_not_fabricated() -> None:
    config = configuration(
        capabilities=HeatDeliveryCapabilities(
            can_set_target_temperature=True,
            can_write_remote_temperature=True,
        ),
        forward_remote_temperature=True,
    )
    port = RecordingPort()
    controller = ZoneHeatDeliveryController((config,), {config.actuator_id: port})
    evaluate(controller, BuildingHeatDemandStatus.HEAT_REQUIRED, measurement=20.4)
    assert [(command.kind, command.value) for command in port.commands] == [
        (HeatDeliveryCommandKind.SET_TARGET_TEMPERATURE, 30.0),
        (HeatDeliveryCommandKind.WRITE_REMOTE_TEMPERATURE, 20.4),
    ]
    evaluate(controller, BuildingHeatDemandStatus.INDETERMINATE, measurement=None)
    assert len(port.commands) == 2


def test_reported_state_is_separate_and_disagreement_is_observable() -> None:
    config = configuration()
    port = RecordingPort()
    controller = ZoneHeatDeliveryController((config,), {config.actuator_id: port})
    evaluate(controller, BuildingHeatDemandStatus.HEAT_REQUIRED)
    state = controller.record_reported_state(config.actuator_id, target_temperature=28.0, position=47.0)
    assert state.commanded_target_temperature == 30.0
    assert state.reported_target_temperature == 28.0
    assert state.reported_position == 47.0
    assert state.commanded_position is None
    assert state.actuator_failure_active is True


def test_two_zones_and_multiple_actuators_are_independent_and_stably_ordered() -> None:
    a2 = configuration("a2")
    a1 = configuration("a1")
    b = configuration("b1", zone_id=ZONE_B, mode=HeatDeliveryMode.NATIVE)
    ports = {item.actuator_id: RecordingPort() for item in (a2, a1, b)}
    controller = ZoneHeatDeliveryController((b, a2, a1), ports)
    assert [(state.zone_id.value, state.actuator_id.value) for state in controller.states] == [
        ("zone_a", "a1"),
        ("zone_a", "a2"),
        ("zone_b", "b1"),
    ]
    evaluate(controller, BuildingHeatDemandStatus.HEAT_REQUIRED)
    evaluate(controller, BuildingHeatDemandStatus.NO_HEAT_REQUIRED, zone_id=ZONE_B)
    assert [command.value for command in ports[a1.actuator_id].commands] == [30.0]
    assert [command.value for command in ports[a2.actuator_id].commands] == [30.0]
    assert [command.value for command in ports[b.actuator_id].commands] == [22.0]
