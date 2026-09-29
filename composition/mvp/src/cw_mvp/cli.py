"""``cw-mvp``: the commands of the one deployable.

- ``cw-mvp serve`` runs the app process (``cw_mvp.serve``): every service's HTTP API on the
  public and the internal listener.
"""

import argparse
from collections.abc import Callable, Sequence

from cw_mvp import serve as serve_module

PROG = "cw-mvp"


def _serve(_: argparse.Namespace) -> int:
    serve_module.serve()
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog=PROG, description="ComplianceWatch in one deployable.")
    commands = root.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the app process on both listeners")
    serve.set_defaults(run=_serve)
    return root


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    run: Callable[[argparse.Namespace], int] = args.run
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
