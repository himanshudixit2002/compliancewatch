"""What can go wrong when the pipeline hands regulator records and their embeddings to the
rulebook, keeps fetched files in the raw store, or looks a source up, and what its API refuses.

The pipeline's own failures are plain exceptions: they cross Temporal as failure types, and the
activities list the ones a retry cannot fix as non-retryable. What the API answers with a problem
is a ``DomainError`` (the end of this module), mapped to its status in ``pipeline.main``.
"""

from domain_kernel.errors import DomainError


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


class RawStoreError(Exception):
    """The raw store did not store or return a file: refused, unreachable or failing after its
    retries. Worth retrying unless a subclass says otherwise."""


class RawObjectMissingError(RawStoreError):
    """No file is stored under the key. A record names it, so the store lost it or the
    deployment points at another store; retrying cannot help."""


class RawObjectCorruptError(RawStoreError):
    """The stored bytes do not have the digest their key names; retrying cannot help."""


class UnknownSourceError(LookupError):
    """No source with this id is known to the pipeline; retrying cannot help."""


class SourceNotFoundError(DomainError, LookupError):
    """No source has this key."""

    type_slug = "pipeline-source-not-found"
    title = "Source not found"


class SourceExistsError(DomainError):
    """A source with this key exists already."""

    type_slug = "pipeline-source-exists"
    title = "Source exists already"


class SourceInvalidError(DomainError, ValueError):
    """The adapter type is unknown, or its parameters are not what the type takes."""

    type_slug = "pipeline-source-invalid"
    title = "Source is not valid"


class DocumentNotFoundError(DomainError, LookupError):
    """No stored document has this id."""

    type_slug = "pipeline-document-not-found"
    title = "Stored document not found"


class RawDocumentUnreadableError(DomainError):
    """The raw store has no file under the document's key, or its bytes have another digest than
    the record names: the file was lost or altered, and serving it would serve something else."""

    type_slug = "pipeline-raw-document-unreadable"
    title = "The stored file cannot be served"


class RawStoreUnavailableError(DomainError):
    """The raw store did not answer; worth asking again."""

    type_slug = "pipeline-raw-store-unavailable"
    title = "The raw store is unavailable"


class CrawlDisabledError(DomainError):
    """Crawling is off (``CW_PIPELINE_CRAWL_ENABLED``): no crawl starts."""

    type_slug = "pipeline-crawl-disabled"
    title = "Crawling is off"

    def __init__(self) -> None:
        super().__init__(
            "crawling is off (CW_PIPELINE_CRAWL_ENABLED); no crawl starts and no regulator site "
            "is read"
        )


class CrawlRunningError(DomainError):
    """A crawl of the source is running; a second one waits for it to end."""

    type_slug = "pipeline-crawl-running"
    title = "A crawl of this source is running"


class CrawlUnavailableError(DomainError):
    """The crawl could not be started: Temporal did not answer."""

    type_slug = "pipeline-crawl-unavailable"
    title = "The crawl could not be started"


class WriteTokenInvalidError(DomainError, PermissionError):
    type_slug = "pipeline-write-token-invalid"
    title = "Pipeline write token missing or wrong"

    def __init__(self) -> None:
        super().__init__(
            "pipeline writes need the x-cw-write-token header with the shared write token "
            "(CW_RULEBOOK_WRITE_TOKEN)"
        )


class WritesDisabledError(DomainError, PermissionError):
    """No write token is configured, so writes are refused: the pipeline fails closed."""

    type_slug = "pipeline-writes-disabled"
    title = "Pipeline writes are not configured"

    def __init__(self) -> None:
        super().__init__(
            "pipeline writes are refused: CW_RULEBOOK_WRITE_TOKEN is not set, so no shared write "
            "token opens them"
        )
