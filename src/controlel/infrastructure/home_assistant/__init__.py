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
]
