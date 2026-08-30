"""Unit tests for the unconfigured Frontend API evidence source."""

from controlel.frontend_api.v1 import frontend_response_to_dict
from custom_components.controlel.core_capabilities import water_safety_core_available
from custom_components.controlel.frontend_api import create_unconfigured_frontend_api_provider_v1


def test_unconfigured_provider_reports_inactive_modules_and_ready_setup() -> None:
    provider = create_unconfigured_frontend_api_provider_v1()
    overview = frontend_response_to_dict(provider.overview())
    heating = frontend_response_to_dict(provider.heating())
    setup = frontend_response_to_dict(provider.setup())

    assert overview["system"]["status"] == "stopped"
    assert overview["system"]["operating_mode"] == "UNCONFIGURED"
    expected_modules = [
        {"module_id": "heating", "status": "inactive", "reason": "heating_not_configured"},
    ]
    if water_safety_core_available():
        expected_modules.append(
            {
                "module_id": "water_safety",
                "status": "inactive",
                "reason": "water_safety_not_configured",
            },
        )
    assert overview["modules"] == expected_modules
    assert heating["zones"] == []
    assert setup["readiness"] == {"state": "ready", "reason_code": None}

    if water_safety_core_available():
        water = frontend_response_to_dict(provider.water_safety())
        assert water["state"] == "DISABLED"
        assert water["actions_available"] == []
