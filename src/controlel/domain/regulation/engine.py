from controlel.domain.decisions.decision import Decision
from controlel.domain.regulation.context import ControlContext


class RegulationEngine:
    """
    Evaluates control context and produces a decision.
    """

    @staticmethod
    def evaluate(context: ControlContext) -> Decision:
        lower_limit = context.target_temperature.value - context.hysteresis.value

        if context.current_temperature.value < lower_limit:
            return Decision(action="enable_heating")

        return Decision(action="disable_heating")
