"""Embed the stored clauses that have no vector yet, across every document.

``pipeline-embed [--model creator/model] [--limit N]`` runs the ingest workflow's embedding
stage over the whole rulebook: it catches up the clauses registered before the workflow embedded
them, and with ``--model`` fills a new model's vectors ahead of a switch of the gateway's
retrieval route (``CW_LLM_ROUTES__RETRIEVAL``), so search keeps working across the change.
It prints the model the run pinned and the counts. It reads ``CW_RULEBOOK_URL``,
``CW_RULEBOOK_WRITE_TOKEN`` and ``CW_LLM_GATEWAY_URL`` like the worker; running it is the
decision, so ``CW_PIPELINE_KNOWLEDGE_ENABLED`` does not apply.
"""

import argparse
import sys
from collections.abc import Sequence

from pipeline.application.embedding import EmbeddingStage
from pipeline.infrastructure.gateway import GatewayEmbedder
from pipeline.infrastructure.rulebook_client import HttpRulebook
from pipeline.settings import PipelineSettings

SERVICE_NAME = "pipeline-embed"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pipeline-embed", description=__doc__)
    parser.add_argument("--model", default=None, help="override the gateway's retrieval model")
    parser.add_argument("--limit", type=int, default=None, help="embed at most this many")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")
    settings = PipelineSettings(service_name=SERVICE_NAME)
    token = settings.rulebook_write_token
    rulebook = HttpRulebook(
        settings.rulebook_url, token=None if token is None else token.get_secret_value()
    )
    embedder = GatewayEmbedder(settings.llm_gateway_url)
    try:
        run = EmbeddingStage(embedder, rulebook).embed_missing(
            None, limit=args.limit, model=args.model, metadata={"run": SERVICE_NAME}
        )
    finally:
        embedder.close()
        rulebook.close()
    sys.stdout.write(f"{run.model}: embedded {run.embedded}, unchanged {run.unchanged}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
