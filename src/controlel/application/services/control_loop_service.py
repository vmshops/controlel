from controlel.application.services.regulation_service import RegulationService
from controlel.domain.events.decision_event import DecisionCreatedEvent
from controlel.domain.regulation.context import ControlContext


class ControlLoopService:
    """
    Application service responsible for running the control loop.

    Converts regulation results into domain events.
    """

    def __init__(self):
        self.regulation_service = RegulationService()

    def process(self, context: ControlContext) -> DecisionCreatedEvent:
        decision = self.regulation_service.evaluate(context)

        return DecisionCreatedEvent(
            decision=decision,
        )
