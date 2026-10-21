"""Application exceptions. Messages on these exceptions are safe to show to users."""


class LeaveFlowError(Exception):
    """Base class for errors whose message can be displayed to the user."""


class BusinessRuleError(LeaveFlowError):
    """A business rule was violated (e.g. insufficient balance)."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


class PermissionDenied(LeaveFlowError):
    """The acting user is not allowed to perform this operation."""


class WorkflowError(LeaveFlowError):
    """An illegal workflow transition was attempted."""


class AuthenticationError(LeaveFlowError):
    """Login failed."""
