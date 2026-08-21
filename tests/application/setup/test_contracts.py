import json
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from controlel.application.setup import (
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    IdentityQuality,
    ProviderReference,
)

from .conftest import NOW, provider_reference


def test_provider_reference_keeps_registry_identity_separate_from_mutable_locator() -> None:
    original = provider_reference("registry-entry-1", "sensor.room")
    renamed = original.model_copy(update={"current_locator": "sensor.renamed_room"})

    assert original.semantic_data() == renamed.semantic_data()
    assert original.current_locator != renamed.current_locator
    assert original.native_id == "registry-entry-1"
    assert original.device_registry_id == "device-room"
    assert original.area_id == "living-room"
    assert original.floor_id == "ground-floor"
    assert original.recovery_evidence["unique_id"] == "unique-registry-entry-1"


def test_ephemeral_reference_cannot_claim_stable_identity() -> None:
    with pytest.raises(ValidationError, match="cannot claim a stable native_id"):
        ProviderReference(
            provider="home_assistant",
            provider_instance_id="ha-home",
            object_kind="home_assistant.endpoint",
            native_id="invented-from-name",
            identity_quality=IdentityQuality.EPHEMERAL,
            current_locator="vendor.target",
        )


def test_discovery_snapshot_is_read_only_and_deeply_immutable() -> None:
    capabilities = {"entity-temperature": {"classes": ["measurement.temperature"]}}
    snapshot = DiscoverySnapshot(
        snapshot_id="snapshot-1",
        provider="home_assistant",
        provider_instance_id="ha-home",
        adapter_contract_version="0.1",
        captured_at=NOW,
        objects=(provider_reference("entity-temperature", "sensor.room"),),
        capabilities=capabilities,
    )
    capabilities["entity-temperature"]["classes"].append("command.enable_disable")

    assert snapshot.capabilities["entity-temperature"]["classes"] == ("measurement.temperature",)
    with pytest.raises(TypeError):
        snapshot.capabilities["new"] = "value"  # type: ignore[index]
    assert len(snapshot.content_fingerprint or "") == 64


def test_canonical_json_hash_and_semantic_fingerprint_are_deterministic(
    canonical_revision: CanonicalConfigurationRevision,
) -> None:
    document = json.loads(canonical_revision.canonical_json())
    reconstructed = CanonicalConfigurationRevision.model_validate(document)

    assert reconstructed.canonical_json() == canonical_revision.canonical_json()
    assert reconstructed.document_hash == canonical_revision.document_hash
    assert reconstructed.semantic_configuration_fingerprint == canonical_revision.semantic_configuration_fingerprint
    assert document["created_at"] == "2026-08-21T10:00:00.000000Z"

    equivalent_instant = canonical_revision.model_copy(
        update={"created_at": datetime(2026, 8, 21, 12, 0, tzinfo=timezone(timedelta(hours=2)))}
    )
    equivalent_validated = CanonicalConfigurationRevision.model_validate(equivalent_instant.model_dump(mode="python"))
    assert equivalent_validated.document_hash == canonical_revision.document_hash


def test_canonical_revision_copies_nested_payload_and_evidence(
    canonical_revision: CanonicalConfigurationRevision,
) -> None:
    document = json.loads(canonical_revision.canonical_json())
    reconstructed = CanonicalConfigurationRevision.model_validate(document)
    document["module_payload"]["source_enable"]["domain"] = "mutated"
    document["bindings"][0]["reference"]["recovery_evidence"]["unique_id"] = "mutated"

    assert reconstructed.module_payload["source_enable"]["domain"] == "vendor_boiler"
    assert reconstructed.bindings[0].reference.recovery_evidence["unique_id"] != "mutated"
    with pytest.raises(TypeError):
        reconstructed.module_payload["new"] = True  # type: ignore[index]


def test_canonical_document_rejects_hash_tampering(canonical_revision: CanonicalConfigurationRevision) -> None:
    document = json.loads(canonical_revision.canonical_json())
    document["module_payload"]["target_temperature_celsius"] = 30.0

    with pytest.raises(ValidationError, match="semantic configuration fingerprint does not match"):
        CanonicalConfigurationRevision.model_validate(document)


def test_ephemeral_locator_is_semantic_but_stable_locator_rename_is_not(
    canonical_revision: CanonicalConfigurationRevision,
) -> None:
    stable_document = json.loads(canonical_revision.canonical_json())
    stable_document["bindings"][0]["reference"]["current_locator"] = "sensor.renamed_room"
    stable_document.pop("document_hash")
    stable_document.pop("semantic_configuration_fingerprint")
    stable_renamed = CanonicalConfigurationRevision.model_validate(stable_document)

    assert stable_renamed.semantic_configuration_fingerprint == canonical_revision.semantic_configuration_fingerprint
    assert stable_renamed.document_hash != canonical_revision.document_hash

    ephemeral_a_document = json.loads(canonical_revision.canonical_json())
    reference = ephemeral_a_document["bindings"][0]["reference"]
    reference["native_id"] = None
    reference["identity_quality"] = "EPHEMERAL"
    reference["current_locator"] = "sensor.room_a"
    ephemeral_a_document.pop("document_hash")
    ephemeral_a_document.pop("semantic_configuration_fingerprint")
    ephemeral_a = CanonicalConfigurationRevision.model_validate(ephemeral_a_document)
    ephemeral_b_document = json.loads(ephemeral_a.canonical_json())
    ephemeral_b_document["bindings"][0]["reference"]["current_locator"] = "sensor.room_b"
    ephemeral_b_document.pop("document_hash")
    ephemeral_b_document.pop("semantic_configuration_fingerprint")
    ephemeral_b = CanonicalConfigurationRevision.model_validate(ephemeral_b_document)

    assert ephemeral_a.semantic_configuration_fingerprint != ephemeral_b.semantic_configuration_fingerprint


def test_confirmation_and_provenance_do_not_change_runtime_semantic_fingerprint(
    canonical_revision: CanonicalConfigurationRevision,
) -> None:
    document = json.loads(canonical_revision.canonical_json())
    document["bindings"][0]["user_confirmed"] = False
    document["bindings"][0]["selection_origin"] = "IMPORTED"
    document["bindings"][0]["provenance"] = {"source": "backup"}
    document.pop("document_hash")
    document.pop("semantic_configuration_fingerprint")
    provenance_changed = CanonicalConfigurationRevision.model_validate(document)

    assert (
        provenance_changed.semantic_configuration_fingerprint == canonical_revision.semantic_configuration_fingerprint
    )
    assert provenance_changed.document_hash != canonical_revision.document_hash


def test_discovery_order_is_deterministic_when_primary_sort_keys_collide() -> None:
    first = provider_reference("same-entry", "sensor.room").model_copy(update={"recovery_evidence": {"unique_id": "a"}})
    second = provider_reference("same-entry", "sensor.room").model_copy(
        update={"recovery_evidence": {"unique_id": "b"}}
    )
    forward = DiscoverySnapshot(
        snapshot_id="forward",
        provider="home_assistant",
        provider_instance_id="ha-home",
        adapter_contract_version="0.1",
        captured_at=NOW,
        objects=(first, second),
    )
    reversed_snapshot = DiscoverySnapshot(
        snapshot_id="reverse",
        provider="home_assistant",
        provider_instance_id="ha-home",
        adapter_contract_version="0.1",
        captured_at=NOW,
        objects=(second, first),
    )

    assert forward.objects == reversed_snapshot.objects
    assert forward.content_fingerprint == reversed_snapshot.content_fingerprint
