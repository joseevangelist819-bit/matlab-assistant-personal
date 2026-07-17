class WorkflowError(Exception):
    pass


class InvalidStateError(WorkflowError):
    pass


class ConflictError(WorkflowError):
    pass


class PolicyError(WorkflowError):
    pass


class NotFoundError(WorkflowError):
    pass
