"""Optional Home Assistant infrastructure adapters."""

from controlel.infrastructure.home_assistant.setup_discovery import (
    HomeAssistantDiscoveryAdapter,
    HomeAssistantEphemeralEndpoint,
    HomeAssistantReferenceResolver,
)

__all__ = [
    "HomeAssistantDiscoveryAdapter",
    "HomeAssistantEphemeralEndpoint",
    "HomeAssistantReferenceResolver",
]
