"""Optional Home Assistant infrastructure adapters."""

from controlel.infrastructure.home_assistant.setup_discovery import (
    HomeAssistantDiscoveryAdapter,
    HomeAssistantEphemeralEndpoint,
    HomeAssistantReferenceResolver,
)
from controlel.infrastructure.home_assistant.setup_host import (
    DiscoverySnapshotDTO,
    HeatingBindingSelectionRequest,
    HeatingSetupHostService,
    HeatingSetupSessionDTO,
    LegacyConfigurationStatusDTO,
    SetupValidationStatus,
)
from controlel.infrastructure.home_assistant.setup_persistence import (
    ACTIVE_REFERENCE_KEY,
    SETUP_STORAGE_VERSION,
    ConfigEntryActiveReferenceStore,
    HomeAssistantSetupRepository,
    SetupStorageIntegrityError,
    is_explicit_legacy_v3_conversion,
)
from controlel.infrastructure.home_assistant.water_safety_discovery import async_snapshot_with_notify_services
from controlel.infrastructure.home_assistant.water_safety_setup_host import (
    WaterSafetyBindingSelectionRequest,
    WaterSafetySetupHostService,
    WaterSafetySetupSessionDTO,
)

__all__ = [
    "HomeAssistantDiscoveryAdapter",
    "HomeAssistantEphemeralEndpoint",
    "HomeAssistantReferenceResolver",
    "ACTIVE_REFERENCE_KEY",
    "SETUP_STORAGE_VERSION",
    "ConfigEntryActiveReferenceStore",
    "DiscoverySnapshotDTO",
    "HeatingBindingSelectionRequest",
    "HeatingSetupHostService",
    "HeatingSetupSessionDTO",
    "HomeAssistantSetupRepository",
    "LegacyConfigurationStatusDTO",
    "SetupStorageIntegrityError",
    "SetupValidationStatus",
    "is_explicit_legacy_v3_conversion",
    "WaterSafetyBindingSelectionRequest",
    "WaterSafetySetupHostService",
    "WaterSafetySetupSessionDTO",
    "async_snapshot_with_notify_services",
]
