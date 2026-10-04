"""``cw-mvp``: the commands of the one deployable.

- ``cw-mvp serve`` runs the app process (``cw_mvp.serve``): every service's HTTP API on the
  public and the internal listener.
- ``cw-mvp worker [--internal-url URL]`` runs the worker process (``cw_mvp.worker``): every
  service's consumers, periodic jobs and Temporal workers and the outbox relays, calling the
  other services at ``URL`` (the app process's internal listener; ``CW_MVP_INTERNAL_URL`` by
  default). It exits 1 when one of them fails.
"""

import argparse
from collections.abc import Callable, Sequence

from cw_mvp import serve as serve_module
from cw_mvp import worker as worker_module

PROG = "cw-mvp"


def _serve(_: argparse.Namespace) -> int:
    serve_module.serve()
    return 0


def _worker(args: argparse.Namespace) -> int:
    return worker_module.main(internal_url=args.internal_url)


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
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    run: Callable[[argparse.Namespace], int] = args.run
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
