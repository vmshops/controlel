class RuntimeStoppedError(RuntimeError):
    """Raised when an operation is attempted after terminal runtime shutdown."""


class RuntimeReentrancyError(RuntimeError):
    """Raised immediately when another runtime operation owns execution."""

    def __init__(
        self,
        active_operation: str,
        attempted_operation: str,
    ) -> None:
        self.active_operation = active_operation
        self.attempted_operation = attempted_operation
        super().__init__(f"Runtime operation '{attempted_operation}' cannot start while '{active_operation}' is active")
