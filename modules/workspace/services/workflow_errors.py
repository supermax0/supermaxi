from __future__ import annotations


class WorkflowError(Exception):
    """Base workflow error."""


class WorkflowNotFoundError(WorkflowError):
    pass


class WorkflowInvalidStateError(WorkflowError):
    pass


class WorkflowInvalidTypeError(WorkflowError):
    pass


class WorkflowInputRequiredError(WorkflowError):
    pass


class WorkflowApprovalRequiredError(WorkflowError):
    pass
