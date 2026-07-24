"""Home Assistant logging and Repairs boundary for runtime failures."""

import logging
from collections.abc import Callable
from typing import Any

from controlel.application.ports.scheduled_runtime_failure_sink import (
    ScheduledRuntimeFailure,
)

from .const import (
    DOMAIN,
    FATAL_RUNTIME_ISSUE_SUFFIX,
    RECOVERABLE_SERVICE_ISSUE_SUFFIX,
)
from .event_loop_bridge import HomeAssistantEventLoopBridge
from .heat_source import HomeAssistantServiceCallError

type CreateIssue = Callable[..., None]
type DeleteIssue = Callable[[object, str, str], None]
type FatalHandler = Callable[[Exception], None]


class HomeAssistantScheduledFailureSink:
    def __init__(
        self,
        hass: object,
        bridge: HomeAssistantEventLoopBridge,
        entry_id: str,
        logger: logging.Logger,
        create_issue: CreateIssue | None = None,
        delete_issue: DeleteIssue | None = None,
        warning_severity: object | None = None,
        error_severity: object | None = None,
    ) -> None:
        self._hass = hass
        self._bridge = bridge
        self._entry_id = entry_id
        self._logger = logger
        self._create_issue = create_issue or _default_create_issue
        self._delete_issue = delete_issue or _default_delete_issue
        self._warning_severity = warning_severity
        self._error_severity = error_severity
        self._fatal_handler: FatalHandler | None = None
        self.last_failure: ScheduledRuntimeFailure | None = None
        self.last_synchronous_error: Exception | None = None

    @property
    def recoverable_issue_id(self) -> str:
        return f"{self._entry_id}_{RECOVERABLE_SERVICE_ISSUE_SUFFIX}"

    @property
    def fatal_issue_id(self) -> str:
        return f"{self._entry_id}_{FATAL_RUNTIME_ISSUE_SUFFIX}"

    def bind_fatal_handler(self, handler: FatalHandler) -> None:
        if self._fatal_handler is not None:
            raise RuntimeError("fatal failure handler is already bound")
        self._fatal_handler = handler

    def report(self, failure: ScheduledRuntimeFailure) -> None:
        self.last_failure = failure
        self._bridge.call_soon(self._handle_scheduled_failure, failure)

    def handle_synchronous_failure(self, error: Exception) -> None:
        """Handle a non-scheduled failure directly on the HA event loop."""
        self.last_synchronous_error = error
        self._handle_error(error)

    def clear_service_failure_issue(self) -> None:
        self._bridge.call_soon(self._delete_recoverable_issue)

    def clear_fatal_issue_after_successful_reload(self) -> None:
        self._delete_issue(self._hass, DOMAIN, self.fatal_issue_id)

    def clear_transient_issues(self) -> None:
        self._delete_recoverable_issue()

    def _handle_scheduled_failure(
        self,
        failure: ScheduledRuntimeFailure,
    ) -> None:
        self._handle_error(failure.error)

    def _handle_error(self, error: Exception) -> None:
        if isinstance(error, HomeAssistantServiceCallError):
            self._logger.error(
                "Controlel heat-source service call failed",
                exc_info=(type(error), error, error.__traceback__),
            )
            self._create_issue(
                self._hass,
                DOMAIN,
                self.recoverable_issue_id,
                is_fixable=False,
                severity=(self._warning_severity if self._warning_severity is not None else _issue_severity_warning()),
                translation_key="heat_source_service_failure",
                translation_placeholders={"error": str(error)},
            )
            return

        self._logger.error(
            "Fatal Controlel runtime failure",
            exc_info=(type(error), error, error.__traceback__),
        )
        self._create_issue(
            self._hass,
            DOMAIN,
            self.fatal_issue_id,
            is_fixable=False,
            severity=(self._error_severity if self._error_severity is not None else _issue_severity_error()),
            translation_key="fatal_runtime_failure",
            translation_placeholders={"error": str(error)},
        )
        if self._fatal_handler is not None:
            self._fatal_handler(error)

    def _delete_recoverable_issue(self) -> None:
        self._delete_issue(self._hass, DOMAIN, self.recoverable_issue_id)


def _default_create_issue(*args: Any, **kwargs: Any) -> None:
    from homeassistant.helpers.issue_registry import async_create_issue

    async_create_issue(*args, **kwargs)


def _default_delete_issue(hass: object, domain: str, issue_id: str) -> None:
    from homeassistant.helpers.issue_registry import async_delete_issue

    async_delete_issue(hass, domain, issue_id)


def _issue_severity_warning() -> object:
    from homeassistant.helpers.issue_registry import IssueSeverity

    return IssueSeverity.WARNING


def _issue_severity_error() -> object:
    from homeassistant.helpers.issue_registry import IssueSeverity

    return IssueSeverity.ERROR
