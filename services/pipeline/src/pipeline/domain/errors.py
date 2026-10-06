"""What can go wrong when the pipeline hands regulator records and their embeddings to the
rulebook, keeps fetched files in the raw store, parses a document or looks a source up, and what
its API refuses.

The pipeline's own failures are plain exceptions: they cross Temporal as failure types, and the
activities list the ones a retry cannot fix as non-retryable. What the API answers with a problem
is a ``DomainError`` (the end of this module), mapped to its status in ``pipeline.main``.
"""

from domain_kernel.errors import DomainError


class RulebookConflictError(Exception):
    """The rulebook stores this document with other clauses from the same parser version: the
    parser changed what it gives for the same bytes without a new version. Retrying cannot help.
    The stored clauses stay, because mentions and citations point at them (ADR-018); a parse by
    another parser version is answered with the stored one instead."""


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


class UnparsedDocumentError(ValueError):
    """No parser of the chain could read the document's bytes: a PDF with no text layer (a scan,
    which needs OCR or a person), or bytes a parser could not open. The ingest opens a
    manual-parse task for it; retrying cannot help."""


class UnsupportedDocumentError(Exception):
    """No parser of the chain takes the document's media type; retrying cannot help."""


class TranscriptInvalidError(DomainError, ValueError):
    """An analyst's transcript is not in the shape of the parsers' blocks, or gives clauses the
    rulebook would refuse; the message names each problem by its place."""

    type_slug = "pipeline-transcript-invalid"
    title = "The transcript is not valid"


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


class SourceNotListableError(DomainError):
    """The source is upload-only (its adapter type lists nothing): there is no crawl to start;
    its documents are uploaded."""

    type_slug = "pipeline-source-upload-only"
    title = "The source is upload-only"


class CrawlRunningError(DomainError):
    """A crawl of the source is running; a second one waits for it to end."""

    type_slug = "pipeline-crawl-running"
    title = "A crawl of this source is running"


class CrawlUnavailableError(DomainError):
    """The crawl could not be started: Temporal did not answer."""

    type_slug = "pipeline-crawl-unavailable"
    title = "The crawl could not be started"


class UploadTooLargeError(DomainError):
    """The uploaded file is larger than ``CW_PIPELINE_UPLOAD_MAX_BYTES``."""

    type_slug = "pipeline-upload-too-large"
    title = "The upload is too large"


class UploadUnsupportedError(DomainError):
    """The uploaded file is not a PDF or an HTML page, or its bytes are not what its type says."""

    type_slug = "pipeline-upload-unsupported"
    title = "The upload is not a PDF or an HTML page"


class IngestUnavailableError(DomainError):
    """The ingest could not be started: Temporal did not answer. What was stored stays stored."""

    type_slug = "pipeline-ingest-unavailable"
    title = "The ingest could not be started"


class TaskNotFoundError(DomainError, LookupError):
    """No pipeline task has this id."""

    type_slug = "pipeline-task-not-found"
    title = "Pipeline task not found"


class TaskClosedError(DomainError):
    """The task is resolved or dismissed already; a closed task does not change."""

    type_slug = "pipeline-task-closed"
    title = "The task is closed"


class TaskResolutionError(DomainError, ValueError):
    """The resolution does not fit the task: a manual parse is resolved with a transcript, and
    nothing else takes one."""

    type_slug = "pipeline-task-resolution-invalid"
    title = "The resolution does not fit the task"


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
