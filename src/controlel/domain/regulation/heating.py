from controlel.domain.decisions.decision import Decision
from controlel.domain.decisions.decision_action import DecisionAction
from controlel.domain.regulation.context import ControlContext
from controlel.domain.regulation.strategy import RegulationStrategy


class HeatingStrategy(RegulationStrategy):
    """
    Strategy for heating regulation.
    """

    def evaluate(self, context: ControlContext) -> Decision:
        lower_limit = context.target_temperature.value - context.hysteresis.value

        if context.current_temperature.value < lower_limit:
            return Decision(
                sensor_id=context.sensor_id,
                zone_id=context.zone_id,
                action=DecisionAction.ENABLE_HEATING,
            )

        return Decision(
            sensor_id=context.sensor_id,
            zone_id=context.zone_id,
            action=DecisionAction.DISABLE_HEATING,
        )
