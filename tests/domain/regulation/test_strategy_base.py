from controlel.domain.regulation.heating import HeatingStrategy
from controlel.domain.regulation.strategy import RegulationStrategy


def test_heating_strategy_implements_strategy_interface():
    strategy = HeatingStrategy()

    assert isinstance(strategy, RegulationStrategy)
