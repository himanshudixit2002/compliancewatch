"""Errors of the eval service, with stable problem type slugs."""

from domain_kernel.errors import DomainError


class EvalRunNotFoundError(DomainError, LookupError):
    type_slug = "eval-run-not-found"
    title = "Eval run not found"

    def __init__(self, run_id: str) -> None:
        super().__init__(f"eval run {run_id} does not exist")
        self.run_id = run_id


class EvalHarnessError(DomainError, RuntimeError):
    """The harness stopped before it measured the gates: a model call the scripted labels do not
    cover, no labelled cases, a crash or a timeout. Nothing is stored for such a run."""

    type_slug = "eval-harness-failed"
    title = "Eval harness failed"
