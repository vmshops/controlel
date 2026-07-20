from controlel.domain.decisions.decision import Decision
from controlel.domain.regulation.context import ControlContext
from controlel.domain.regulation.strategy import RegulationStrategy


class RegulationEngine:
    """
    Engine responsible for executing regulation strategies.
    """

    def __init__(self, strategy: RegulationStrategy):
        self.strategy = strategy

    def evaluate(self, context: ControlContext) -> Decision:
        return self.strategy.evaluate(context)
