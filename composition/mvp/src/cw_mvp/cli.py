"""``cw-mvp``: the commands of the one deployable.

- ``cw-mvp serve`` runs the app process (``cw_mvp.serve``): every service's HTTP API on the
  public and the internal listener.
- ``cw-mvp worker [--internal-url URL]`` runs the worker process (``cw_mvp.worker``): every
  service's consumers, periodic jobs and Temporal workers and the outbox relays, calling the
  other services at ``URL`` (the app process's internal listener; ``CW_MVP_INTERNAL_URL`` by
  default). It exits 1 when one of them fails.

The release commands (``cw_mvp.release``) exit 1 with the reason when they cannot do their work:

- ``cw-mvp migrate [--service NAME]`` runs ``alembic upgrade head`` for every service schema in
  the registry's order, or one, as the owner (``CW_MIGRATION_DATABASE_URL``), and reports each
  revision (``cw_mvp.migrate``);
- ``cw-mvp topics plan|apply [--file PATH]`` compares ``composition/mvp/topics.toml`` with the
  broker, or creates the topics it lacks (``cw_mvp.topics``);
- ``cw-mvp release`` is a deploy's release step: migrate, then apply the topics;
- ``cw-mvp check-config`` checks the environment against its ``CW_ENV``
  (``cw_mvp.check_config``) and lists every problem it finds.
"""

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path

from cw_mvp import release as release_module
from cw_mvp import serve as serve_module
from cw_mvp import worker as worker_module
from cw_mvp.registry import REGISTRY
from cw_mvp.topics import TOPICS_FILE

PROG = "cw-mvp"


def _serve(_: argparse.Namespace) -> int:
    serve_module.serve()
    return 0


def _worker(args: argparse.Namespace) -> int:
    return worker_module.main(internal_url=args.internal_url)


def _migrate(args: argparse.Namespace) -> int:
    settings = release_module.release_settings()
    if settings is None:
        return 1
    return release_module.run_migrate(settings, services=[args.service] if args.service else [])


def _topics(args: argparse.Namespace) -> int:
    settings = release_module.release_settings()
    if settings is None:
        return 1
    return release_module.run_topics(settings, args.topics_command, path=args.file)


def _release(_: argparse.Namespace) -> int:
    settings = release_module.release_settings()
    if settings is None:
        return 1
    return release_module.run_release(settings)


def _check_config(_: argparse.Namespace) -> int:
    return release_module.run_check_config()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog=PROG, description="ComplianceWatch in one deployable.")
    commands = root.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the app process on both listeners")
    serve.set_defaults(run=_serve)
    worker = commands.add_parser("worker", help="run the worker process")
    worker.add_argument(
        "--internal-url",
        default=None,
        help="where the app process's internal listener is (default CW_MVP_INTERNAL_URL)",
    )
    worker.set_defaults(run=_worker)
    migrate = commands.add_parser(
        "migrate", help="alembic upgrade head for every service schema, as the schemas' owner"
    )
    migrate.add_argument(
        "--service",
        choices=[entry.name for entry in REGISTRY],
        default=None,
        help="migrate this service only",
    )
    migrate.set_defaults(run=_migrate)
    topics = commands.add_parser("topics", help="the Kafka topics of topics.toml")
    topics.add_argument(
        "topics_command",
        choices=["plan", "apply"],
        help="plan: compare with the broker; apply: create the topics the broker lacks",
    )
    topics.add_argument(
        "--file",
        type=Path,
        default=TOPICS_FILE,
        help="the topics file (default composition/mvp/topics.toml)",
    )
    topics.set_defaults(run=_topics)
    release = commands.add_parser(
        "release", help="the release step of a deploy: migrate, then apply the topics"
    )
    release.set_defaults(run=_release)
    check_config = commands.add_parser(
        "check-config", help="check the environment against its CW_ENV and list the problems"
    )
    check_config.set_defaults(run=_check_config)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    run: Callable[[argparse.Namespace], int] = args.run
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
