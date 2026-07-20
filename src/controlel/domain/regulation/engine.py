from controlel.domain.decisions.decision import Decision
from controlel.domain.regulation.context import ControlContext


class RegulationEngine:
    """
    Evaluates control context and produces a decision.
    """

    @staticmethod
    def evaluate(context: ControlContext) -> Decision:
        if context.current_temperature.value < context.target_temperature.value:
            return Decision(action="enable_heating")

        return Decision(action="disable_heating")
