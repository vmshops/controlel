class CommandHandler:
    def __init__(self, actuator):
        self.actuator = actuator

    def handle(self, command):
        self.actuator.execute(command)
