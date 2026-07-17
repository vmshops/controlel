from controlel.domain.commands.command import Command


def test_command_creation():
    command = Command(command_type="test_command")

    assert command.command_type == "test_command"
    assert command.id is not None
    assert command.created_at is not None
