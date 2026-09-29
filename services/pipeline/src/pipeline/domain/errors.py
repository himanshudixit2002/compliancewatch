"""What can go wrong when the pipeline hands regulator records and their embeddings to the
rulebook.

Plain exceptions, like the rest of the pipeline's: they cross Temporal as failure types, and the
activities list the ones a retry cannot fix as non-retryable.
"""


class RulebookConflictError(Exception):
    """The rulebook stores this document with other clauses: a parser change made the same bytes
    parse differently. Retrying cannot help. The stored clauses stay, because mentions and
    citations point at them; what to do with stored documents after a parser change is a
    decision for a person (ADR-018)."""


class RulebookRejectedError(Exception):
    """The rulebook refused the request (malformed, unauthorised, writes disabled)."""


class RulebookUnavailableError(Exception):
    """The rulebook did not answer or failed; worth retrying."""


class KnowledgeContractError(Exception):
    """The rulebook answered with ids the pipeline does not derive for the same input: the two
    disagree about the kernel's id rules, usually a version skew between deployments."""


class EmbeddingContractError(Exception):
    """The gateway answered an embedding call with vectors the rulebook cannot store: another
    length than ``EMBEDDING_DIMS``, another count than the texts sent, or another model than the
    run pinned. The same call gets the same answer, so it is not retried."""
