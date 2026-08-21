"""Module-neutral Setup / Discovery / Import foundation."""

from controlel.application.setup.activation import ActivationCoordinator
from controlel.application.setup.effective import (
    derive_real_runtime_configuration,
    derive_shadow_runtime_configuration,
)
from controlel.application.setup.importer import (
    CanonicalConfigurationImporter,
    CanonicalImportIntegrityError,
    ConfigurationImportResult,
    UnsupportedSetupSchemaVersion,
)
from controlel.application.setup.model import (
    ActivationAttempt,
    ActivationState,
    ActiveReference,
    BindingSelection,
    CandidateRuntimeReady,
    CanonicalConfigurationRevision,
    DiscoverySnapshot,
    DraftRevision,
    EffectiveRuntimeConfiguration,
    IdentityQuality,
    LoadedRuntimeConfiguration,
    ProviderObjectReference,
    ProviderReference,
    RuntimeConfigurationOrigin,
    SelectionOrigin,
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
    ValidationSubjectKind,
)
from controlel.application.setup.repository import (
    InMemorySetupRepository,
    SetupConflictError,
    SetupNotFoundError,
)

__all__ = [
    "ActiveReference",
    "ActivationAttempt",
    "ActivationCoordinator",
    "ActivationState",
    "BindingSelection",
    "CandidateRuntimeReady",
    "CanonicalImportIntegrityError",
    "CanonicalConfigurationRevision",
    "CanonicalConfigurationImporter",
    "ConfigurationImportResult",
    "DiscoverySnapshot",
    "DraftRevision",
    "EffectiveRuntimeConfiguration",
    "IdentityQuality",
    "InMemorySetupRepository",
    "LoadedRuntimeConfiguration",
    "ProviderObjectReference",
    "ProviderReference",
    "RuntimeConfigurationOrigin",
    "SelectionOrigin",
    "SetupConflictError",
    "SetupNotFoundError",
    "UnsupportedSetupSchemaVersion",
    "ValidationIssue",
    "ValidationReport",
    "ValidationSeverity",
    "ValidationSubjectKind",
    "derive_real_runtime_configuration",
    "derive_shadow_runtime_configuration",
]
