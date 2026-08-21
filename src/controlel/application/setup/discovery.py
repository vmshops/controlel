"""Module-neutral discovery resolution result contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from controlel.application.setup.json_data import (
    FrozenJsonMapping,
    ImmutableJsonMapping,
    canonical_json,
    immutable_json_mapping,
)
from controlel.application.setup.model import DiscoverySnapshot, IdentityQuality, ProviderReference


class ReferenceResolutionStatus(StrEnum):
    """Outcome of resolving one persisted provider reference."""

    RESOLVED = "RESOLVED"
    MISSING = "MISSING"
    RECOVERY_CANDIDATE = "RECOVERY_CANDIDATE"
    AMBIGUOUS = "AMBIGUOUS"
    EPHEMERAL = "EPHEMERAL"
    ENVIRONMENT_MISMATCH = "ENVIRONMENT_MISMATCH"


class RecoveryCandidate(BaseModel):
    """A possible replacement supported by evidence but not accepted as identity."""

    reference: ProviderReference
    reason_codes: tuple[str, ...] = Field(min_length=1)
    matched_evidence: ImmutableJsonMapping = Field(default_factory=lambda: FrozenJsonMapping({}))

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("reason_codes", mode="after")
    @classmethod
    def reason_codes_must_be_deterministic(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not reason for reason in value):
            raise ValueError("recovery candidate reason codes must be non-empty")
        return tuple(sorted(set(value)))

    @field_validator("matched_evidence", mode="after")
    @classmethod
    def evidence_must_be_immutable(cls, value: object) -> FrozenJsonMapping:
        return immutable_json_mapping(value, "matched recovery evidence")


class ProviderReferenceResolution(BaseModel):
    """Immutable exact-resolution result; candidates never become implicit bindings."""

    requested_reference: ProviderReference
    status: ReferenceResolutionStatus
    reason_code: str = Field(min_length=1)
    resolved_reference: ProviderReference | None = None
    recovery_candidates: tuple[RecoveryCandidate, ...] = ()

    model_config = ConfigDict(frozen=True, extra="forbid")

    @model_validator(mode="after")
    def resolution_shape_must_be_truthful(self) -> ProviderReferenceResolution:
        candidates = tuple(
            sorted(
                self.recovery_candidates,
                key=lambda candidate: canonical_json(candidate.reference.document_data()),
            )
        )
        object.__setattr__(self, "recovery_candidates", candidates)

        if self.status is ReferenceResolutionStatus.RESOLVED:
            if self.resolved_reference is None or candidates:
                raise ValueError("RESOLVED requires one resolved reference and no candidates")
            if self.requested_reference.identity_quality is not IdentityQuality.STABLE:
                raise ValueError("RESOLVED is reserved for stable references")
            requested_key = _stable_identity(self.requested_reference)
            if _stable_identity(self.resolved_reference) != requested_key:
                raise ValueError("RESOLVED reference must preserve exact stable identity")
        elif self.status is ReferenceResolutionStatus.EPHEMERAL:
            if self.resolved_reference is None or candidates:
                raise ValueError("EPHEMERAL requires one resolved reference and no candidates")
            if self.requested_reference.identity_quality is not IdentityQuality.EPHEMERAL:
                raise ValueError("EPHEMERAL requires an ephemeral requested reference")
            if self.resolved_reference.semantic_data() != self.requested_reference.semantic_data():
                raise ValueError("EPHEMERAL resolution must preserve locator-based identity")
        elif self.status is ReferenceResolutionStatus.RECOVERY_CANDIDATE:
            if self.resolved_reference is not None or len(candidates) != 1:
                raise ValueError("RECOVERY_CANDIDATE requires exactly one non-authoritative candidate")
        elif self.status is ReferenceResolutionStatus.AMBIGUOUS:
            if self.resolved_reference is not None or len(candidates) < 2:
                raise ValueError("AMBIGUOUS requires at least two non-authoritative candidates")
        elif self.resolved_reference is not None or candidates:
            raise ValueError(f"{self.status.value} cannot carry a resolved reference or candidates")

        if self.status in {
            ReferenceResolutionStatus.RECOVERY_CANDIDATE,
            ReferenceResolutionStatus.AMBIGUOUS,
        }:
            requested = self.requested_reference
            for candidate in candidates:
                reference = candidate.reference
                if (
                    reference.provider != requested.provider
                    or reference.provider_instance_id != requested.provider_instance_id
                    or reference.object_kind != requested.object_kind
                    or reference.identity_quality is not IdentityQuality.STABLE
                    or reference.native_id == requested.native_id
                ):
                    raise ValueError("recovery candidates must be new stable identities in the requested scope")
        return self


class ProviderReferenceResolver(Protocol):
    """Provider-neutral resolution port implemented by outer provider adapters."""

    def resolve(
        self,
        reference: ProviderReference,
        snapshot: DiscoverySnapshot,
    ) -> ProviderReferenceResolution: ...


def _stable_identity(reference: ProviderReference) -> tuple[str, str, str, str | None]:
    return (
        reference.provider,
        reference.provider_instance_id,
        reference.object_kind,
        reference.native_id,
    )
