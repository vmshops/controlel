from abc import ABC, abstractmethod

from controlel.domain.decisions.decision import Decision
from controlel.domain.regulation.context import ControlContext


class RegulationStrategy(ABC):
    """
    Base interface for regulation strategies.
    """

    @abstractmethod
    def evaluate(self, context: ControlContext) -> Decision:
        """
        Evaluate current context and return decision.
        """
        raise NotImplementedError
