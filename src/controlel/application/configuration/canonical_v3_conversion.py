"""Explicit review result for non-activating canonical v3 conversion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from controlel.application.configuration.canonical_v3_lifecycle import (
    CanonicalConfigurationDraftV3,
    CanonicalReferenceHealthV3,
)


class CanonicalConfigurationConversionReviewV3(BaseModel):
    """Conversion evidence and an optional schema-valid v3 draft candidate."""

    source_kind: Literal["canonical_v2", "legacy_home_assistant"]
    source_revision_id: str = Field(min_length=1)
    draft: CanonicalConfigurationDraftV3 | None
    source_reference_health: tuple[CanonicalReferenceHealthV3, ...]
    reference_health: tuple[CanonicalReferenceHealthV3, ...]
    issue_codes: tuple[str, ...] = ()
    conversion_ready: bool
    activated: Literal[False] = False

    model_config = ConfigDict(frozen=True, extra="forbid")

    @field_validator("issue_codes", mode="after")
    @classmethod
    def issue_codes_are_deterministic(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(value)))

    @model_validator(mode="after")
    def readiness_requires_a_draft(self) -> CanonicalConfigurationConversionReviewV3:
        if self.conversion_ready != (self.draft is not None):
            raise ValueError("conversion readiness must match v3 draft availability")
        return self
