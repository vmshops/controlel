"""Localized, fail-safe rendering for Home Assistant notification intents."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from string import Formatter

from controlel.domain.notifications import NotificationIntent

from .const import DOMAIN

FALLBACK_TITLE = "Controlel notification"
FALLBACK_MESSAGE = "Controlel generated an operational notification."

_TRANSLATION_PREFIX = f"component.{DOMAIN}.common."
_SAFE_PARAMETER_NAMES = frozenset(
    {
        "command_outcome",
        "correlation_id",
        "deadline",
        "event_code",
        "event_detail_attempt",
        "event_detail_budget",
        "event_detail_transition_history",
        "new_state",
        "previous_state",
        "reason_code",
        "requested_command",
        "source_id",
        "zone_id",
    }
)
_SCALAR_TYPES = (str, int, float, bool)

type TranslationProvider = Callable[[str], Awaitable[Mapping[str, str]]]


@dataclass(frozen=True, slots=True)
class RenderedNotification:
    """One localized payload plus an optional stable fallback diagnostic code."""

    title: str
    message: str
    fallback_code: str | None = None


class HomeAssistantNotificationRenderer:
    """Render localization-neutral core intents using Home Assistant translations."""

    def __init__(self, hass: object, translation_provider: TranslationProvider | None = None) -> None:
        self._hass = hass
        self._translation_provider = translation_provider or self._async_get_translations
        self._translations_by_language: dict[str, Mapping[str, str]] = {}

    async def async_render(self, intent: NotificationIntent) -> RenderedNotification:
        """Render one intent, falling back without exposing codes or exceptions."""

        try:
            language = getattr(getattr(self._hass, "config", None), "language", "en")
            translations = self._translations_by_language.get(language)
            if translations is None:
                translations = await self._translation_provider(language)
                self._translations_by_language[language] = translations
            title_template = _translation(translations, intent.title_code)
            message_template = _translation(translations, intent.message_code)
            if title_template is None or message_template is None:
                return _fallback("notification_translation_missing")
            parameters = _safe_parameters(intent)
            return RenderedNotification(
                _render_template(title_template, parameters),
                _render_template(message_template, parameters),
            )
        except Exception:
            return _fallback("notification_render_failed")

    async def _async_get_translations(self, language: str) -> Mapping[str, str]:
        from homeassistant.helpers import translation

        return await translation.async_get_translations(self._hass, language, "common", {DOMAIN})


def _translation(translations: Mapping[str, str], code: str) -> str | None:
    value = translations.get(f"{_TRANSLATION_PREFIX}{code}", translations.get(code))
    return value if isinstance(value, str) and value.strip() else None


def _safe_parameters(intent: NotificationIntent) -> dict[str, str]:
    candidates: dict[str, object] = {
        "correlation_id": intent.correlation_id,
        "source_id": intent.source_id,
        "zone_id": intent.zone_id,
    }
    candidates.update({parameter.key: parameter.value for parameter in intent.parameters})
    return {
        key: str(value)
        for key, value in candidates.items()
        if key in _SAFE_PARAMETER_NAMES and value is not None and type(value) in _SCALAR_TYPES
    }


def _render_template(template: str, parameters: Mapping[str, str]) -> str:
    rendered: list[str] = []
    for literal, field_name, format_spec, conversion in Formatter().parse(template):
        rendered.append(literal)
        if field_name is None:
            continue
        if field_name not in _SAFE_PARAMETER_NAMES or format_spec or conversion:
            rendered.append("unknown")
            continue
        rendered.append(parameters.get(field_name, "unknown"))
    return "".join(rendered)


def _fallback(code: str) -> RenderedNotification:
    return RenderedNotification(FALLBACK_TITLE, FALLBACK_MESSAGE, code)
