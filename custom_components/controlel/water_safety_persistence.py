"""Durable Home Assistant storage for Water Safety restart state and evidence."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from importlib import import_module
from typing import Any, Protocol, cast

from controlel.application.water_safety.model import (
    WaterOutputCommand,
    WaterOutputCommandResult,
    WaterSafetyEvent,
)
from controlel.domain.water_safety import (
    MoistureCondition,
    MoistureObservation,
    WaterIncident,
    WaterIncidentStatus,
    WaterSafetySnapshot,
    WaterSafetyState,
)

from .event_loop_bridge import HomeAssistantEventLoopBridge

WATER_SAFETY_STATE_STORAGE_VERSION = 1
WATER_SAFETY_EVIDENCE_STORAGE_VERSION = 1
MAX_PERSISTED_EVENTS = 500


class HomeAssistantStorePort(Protocol):
    async def async_load(self) -> Mapping[str, object] | None: ...

    async def async_save(self, data: Mapping[str, object]) -> None: ...


def create_water_safety_state_store(
    hass: object,
    entry_id: str,
    bridge: HomeAssistantEventLoopBridge,
) -> HomeAssistantWaterSafetyStateStore:
    store = _create_store(hass, WATER_SAFETY_STATE_STORAGE_VERSION, f"controlel.water_safety.state.{entry_id}")
    return HomeAssistantWaterSafetyStateStore(store, bridge)


def create_water_safety_evidence_store(
    hass: object,
    entry_id: str,
    bridge: HomeAssistantEventLoopBridge,
) -> HomeAssistantWaterSafetyEvidenceStore:
    store = _create_store(hass, WATER_SAFETY_EVIDENCE_STORAGE_VERSION, f"controlel.water_safety.evidence.{entry_id}")
    return HomeAssistantWaterSafetyEvidenceStore(store, bridge)


def _create_store(hass: object, version: int, key: str) -> HomeAssistantStorePort:
    storage_module = import_module("homeassistant.helpers.storage")
    store_type = getattr(storage_module, "Store")
    return cast(HomeAssistantStorePort, store_type(hass, version, key))


class HomeAssistantWaterSafetyStateStore:
    """Persist the latest restart snapshot through Home Assistant storage."""

    def __init__(self, store: HomeAssistantStorePort, bridge: HomeAssistantEventLoopBridge) -> None:
        self._store = store
        self._bridge = bridge

    def save(self, snapshot: WaterSafetySnapshot) -> None:
        payload = snapshot_to_dict(snapshot)

        async def async_save() -> None:
            await self._store.async_save({"snapshot": payload})

        self._bridge.run_coroutine(async_save)

    async def async_load_snapshot(self) -> WaterSafetySnapshot | None:
        data = await self._store.async_load()
        if data is None:
            return None
        payload = data.get("snapshot")
        if payload is None:
            return None
        if not isinstance(payload, Mapping):
            raise ValueError("persisted Water Safety snapshot is malformed")
        return snapshot_from_dict(payload)


class HomeAssistantWaterSafetyEvidenceStore:
    """Append Water Safety evidence events for diagnostics history."""

    def __init__(self, store: HomeAssistantStorePort, bridge: HomeAssistantEventLoopBridge) -> None:
        self._store = store
        self._bridge = bridge

    def record(self, event: WaterSafetyEvent) -> None:
        payload = event_to_dict(event)

        async def async_record() -> None:
            data = dict(await self._store.async_load() or {})
            events = list(data.get("events", ()))
            events.append(payload)
            if len(events) > MAX_PERSISTED_EVENTS:
                events = events[-MAX_PERSISTED_EVENTS:]
            data["events"] = events
            await self._store.async_save(data)

        self._bridge.run_coroutine(async_record)

    async def async_load_events(self) -> tuple[dict[str, object], ...]:
        data = await self._store.async_load()
        if data is None:
            return ()
        events = data.get("events", ())
        if not isinstance(events, list):
            raise ValueError("persisted Water Safety evidence is malformed")
        return tuple(item for item in events if isinstance(item, Mapping))


def snapshot_to_dict(snapshot: WaterSafetySnapshot) -> dict[str, object]:
    return {
        "environment_id": snapshot.environment_id,
        "module_instance_id": snapshot.module_instance_id,
        "canonical_revision_id": snapshot.canonical_revision_id,
        "semantic_configuration_fingerprint": snapshot.semantic_configuration_fingerprint,
        "sensor_id": snapshot.sensor_id,
        "state": snapshot.state.value,
        "processing_enabled": snapshot.processing_enabled,
        "latest_observation": _observation_to_dict(snapshot.latest_observation),
        "last_confirmed_observation": _observation_to_dict(snapshot.last_confirmed_observation),
        "active_incident": _incident_to_dict(snapshot.active_incident),
        "last_incident": _incident_to_dict(snapshot.last_incident),
        "unavailable_since": _datetime_to_dict(snapshot.unavailable_since),
        "fault_deadline": _datetime_to_dict(snapshot.fault_deadline),
        "next_fault_notification_at": _datetime_to_dict(snapshot.next_fault_notification_at),
        "next_incident_sequence": snapshot.next_incident_sequence,
        "next_command_sequence": snapshot.next_command_sequence,
        "next_event_sequence": snapshot.next_event_sequence,
        "schema_version": snapshot.schema_version,
    }


def snapshot_from_dict(payload: Mapping[str, object]) -> WaterSafetySnapshot:
    return WaterSafetySnapshot(
        environment_id=str(payload["environment_id"]),
        module_instance_id=str(payload["module_instance_id"]),
        canonical_revision_id=str(payload["canonical_revision_id"]),
        semantic_configuration_fingerprint=str(payload["semantic_configuration_fingerprint"]),
        sensor_id=str(payload["sensor_id"]),
        state=WaterSafetyState(str(payload["state"])),
        processing_enabled=bool(payload["processing_enabled"]),
        latest_observation=_observation_from_dict(payload.get("latest_observation")),
        last_confirmed_observation=_observation_from_dict(payload.get("last_confirmed_observation")),
        active_incident=_incident_from_dict(payload.get("active_incident")),
        last_incident=_incident_from_dict(payload.get("last_incident")),
        unavailable_since=_datetime_from_dict(payload.get("unavailable_since")),
        fault_deadline=_datetime_from_dict(payload.get("fault_deadline")),
        next_fault_notification_at=_datetime_from_dict(payload.get("next_fault_notification_at")),
        next_incident_sequence=int(payload.get("next_incident_sequence", 1)),
        next_command_sequence=int(payload.get("next_command_sequence", 1)),
        next_event_sequence=int(payload.get("next_event_sequence", 1)),
        schema_version=int(payload.get("schema_version", 1)),
    )


def event_to_dict(event: WaterSafetyEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "occurred_at": _datetime_to_dict(event.occurred_at),
        "code": event.code.value,
        "previous_state": event.previous_state.value,
        "new_state": event.new_state.value,
        "observation": _observation_to_dict(event.observation),
        "incident_id": event.incident_id,
        "command": _command_to_dict(event.command),
        "command_result": _command_result_to_dict(event.command_result),
        "details": {key: value for key, value in event.details},
    }


def _observation_to_dict(observation: MoistureObservation | None) -> dict[str, object] | None:
    if observation is None:
        return None
    return {
        "sensor_id": observation.sensor_id,
        "condition": observation.condition.value,
        "observed_at": _datetime_to_dict(observation.observed_at),
        "provider_state": observation.provider_state,
    }


def _observation_from_dict(payload: object) -> MoistureObservation | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError("observation payload must be a mapping")
    return MoistureObservation(
        sensor_id=str(payload["sensor_id"]),
        condition=MoistureCondition(str(payload["condition"])),
        observed_at=_datetime_from_dict(payload["observed_at"]) or _raise_missing("observed_at"),
        provider_state=None if payload.get("provider_state") is None else str(payload["provider_state"]),
    )


def _incident_to_dict(incident: WaterIncident | None) -> dict[str, object] | None:
    if incident is None:
        return None
    return {
        "incident_id": incident.incident_id,
        "status": incident.status.value,
        "started_at": _datetime_to_dict(incident.started_at),
        "last_confirmed_wet_at": _datetime_to_dict(incident.last_confirmed_wet_at),
        "recovered_at": _datetime_to_dict(incident.recovered_at),
        "silenced_at": _datetime_to_dict(incident.silenced_at),
    }


def _incident_from_dict(payload: object) -> WaterIncident | None:
    if payload is None:
        return None
    if not isinstance(payload, Mapping):
        raise ValueError("incident payload must be a mapping")
    return WaterIncident(
        incident_id=str(payload["incident_id"]),
        status=WaterIncidentStatus(str(payload["status"])),
        started_at=_datetime_from_dict(payload["started_at"]) or _raise_missing("started_at"),
        last_confirmed_wet_at=_datetime_from_dict(payload["last_confirmed_wet_at"])
        or _raise_missing("last_confirmed_wet_at"),
        recovered_at=_datetime_from_dict(payload.get("recovered_at")),
        silenced_at=_datetime_from_dict(payload.get("silenced_at")),
    )


def _command_to_dict(command: WaterOutputCommand | None) -> dict[str, object] | None:
    if command is None:
        return None
    return {
        "command_id": command.command_id,
        "requested_at": _datetime_to_dict(command.requested_at),
        "owner": {
            "environment_id": command.owner.environment_id,
            "module_key": command.owner.module_key,
            "module_instance_id": command.owner.module_instance_id,
        },
        "output_kind": command.output_kind.value,
        "action": command.action.value,
        "target_role": command.target_role,
        "target": command.target.model_dump(mode="json"),
        "incident_id": command.incident_id,
        "message_code": command.message_code,
        "custom_message": command.custom_message,
        "repeated": command.repeated,
    }


def _command_result_to_dict(result: WaterOutputCommandResult | None) -> dict[str, object] | None:
    if result is None:
        return None
    return {
        "command_id": result.command_id,
        "occurred_at": _datetime_to_dict(result.occurred_at),
        "outcome": result.outcome.value,
        "failure_code": result.failure_code,
    }


def _datetime_to_dict(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _datetime_from_dict(value: object) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(str(value))


def _raise_missing(label: str) -> Any:
    raise ValueError(f"{label} must not be null")
