from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.demands.zone_demand import ZoneDemand
from controlel.domain.events.decision_event import DecisionCreatedEvent

_REQUIRES_HEAT_BY_ACTION: dict[DecisionAction, bool | None] = {
    DecisionAction.ENABLE_HEATING: True,
    DecisionAction.DISABLE_HEATING: False,
    DecisionAction.OBSERVE_ONLY: None,
}


class ZoneDemandHandler:
    def handle(self, event: DecisionCreatedEvent) -> ZoneDemand | None:
        decision = event.decision
        try:
            requires_heat = _REQUIRES_HEAT_BY_ACTION[decision.action]
        except KeyError:
            raise ValueError(f"Unhandled DecisionAction: {decision.action!r}") from None

        if requires_heat is None:
            return None

        return ZoneDemand(
            zone_id=decision.zone_id,
            requires_heat=requires_heat,
            source_sensor_id=decision.sensor_id,
            observed_at=decision.observed_at,
        )
