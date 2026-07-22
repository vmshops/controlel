from typing import Protocol

from controlel.domain.commands.heat_source_command import HeatSourceCommand


class HeatSourcePort(Protocol):
    def execute(self, command: HeatSourceCommand) -> None: ...
