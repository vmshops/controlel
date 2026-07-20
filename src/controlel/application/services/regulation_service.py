from controlel.domain.decisions.decision import Decision
from controlel.domain.regulation.context import ControlContext
from controlel.domain.regulation.engine import RegulationEngine
from controlel.domain.regulation.heating import HeatingStrategy


class RegulationService:
    def __init__(self) -> None:
        self.engine = RegulationEngine(
            strategy=HeatingStrategy(),
        )

    def evaluate(self, context: ControlContext) -> Decision:
        return self.engine.evaluate(context)
