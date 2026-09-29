"""``identity-admin``: what an operator runs against the identity service's keys and store.

::

    identity-admin signing-key new --kid 2026-10
    identity-admin service-client create --id pipeline --scope rulebook:write --scope llm:call
    identity-admin service-client revoke --id pipeline
    identity-admin service-client list

``signing-key new`` prints a key set with one new ES256 key, the JSON ``CW_IDENTITY_SIGNING_KEYS``
takes; it touches no store. To rotate, put the new record second in the environment's key set,
wait longer than verifiers cache keys (an hour), then move it to the front and drop the old one
once no token it signed is still alive.

``service-client create`` prints the client and its secret as JSON, once: store the secret on the
caller as ``CW_SERVICE_CLIENT_SECRET``; the store keeps only its SHA-256. ``revoke`` stops new
tokens at once; tokens already issued expire within the token lifetime. ``list`` shows ids,
scopes and dates, never a secret. The service-client commands use the database at
``CW_DATABASE_URL``, whose search_path must name the identity schema, as ``make migrate`` sets it.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from typing import TextIO

from domain_kernel.access import Scope
from domain_kernel.errors import DomainError
from identity.application.bootstrap import (
    CreateServiceClient,
    ListServiceClients,
    RevokeServiceClient,
)
from identity.domain.repository import UnitOfWorkFactory
from identity.domain.service_clients import ServiceClient
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from py_common.auth import KeySet, generate_signing_key
from py_common.settings import Settings

PROG = "identity-admin"


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog=PROG, description=__doc__.split("\n\n")[0])
    commands = root.add_subparsers(dest="command", required=True)

    signing_key = commands.add_parser("signing-key", help="ES256 keys for access tokens")
    key_commands = signing_key.add_subparsers(dest="action", required=True)
    new_key = key_commands.add_parser("new", help="print a key set with one new key")
    new_key.add_argument("--kid", required=True, help="the key id, such as the month: 2026-10")

    client = commands.add_parser("service-client", help="clients that get service tokens")
    client_commands = client.add_subparsers(dest="action", required=True)
    create = client_commands.add_parser("create", help="create a client; prints its secret once")
    create.add_argument("--id", required=True, dest="client_id")
    create.add_argument(
        "--scope",
        action="append",
        default=[],
        dest="scopes",
        choices=[scope.value for scope in Scope],
        help="a scope the client may use; repeat for more",
    )
    revoke = client_commands.add_parser("revoke", help="revoke a client")
    revoke.add_argument("--id", required=True, dest="client_id")
    client_commands.add_parser("list", help="list the clients, never their secrets")
    return root


def main(
    argv: Sequence[str] | None = None,
    *,
    unit_of_work: UnitOfWorkFactory | None = None,
    out: TextIO | None = None,
) -> int:
    """Run one command. ``unit_of_work`` replaces the Postgres store (tests)."""
    args = parser().parse_args(argv)
    stream = out or sys.stdout
    try:
        if args.command == "signing-key":
            return _new_signing_key(args.kid, stream)
        store = unit_of_work or PostgresUnitOfWorkFactory.from_url(
            Settings(service_name="identity-admin").database_url
        )
        return _service_client(args, store, stream)
    except (DomainError, ValueError) as exc:
        sys.stderr.write(f"{PROG}: {exc}\n")
        return 1


def _new_signing_key(kid: str, out: TextIO) -> int:
    out.write(KeySet((generate_signing_key(kid),)).dumps() + "\n")
    return 0


def _service_client(args: argparse.Namespace, store: UnitOfWorkFactory, out: TextIO) -> int:
    if args.action == "create":
        scopes = frozenset(Scope(value) for value in args.scopes)
        client, secret = CreateServiceClient(store).run(args.client_id, scopes)
        out.write(json.dumps({**_describe(client), "client_secret": secret}, indent=2) + "\n")
        sys.stderr.write(
            f"{PROG}: the secret is shown once; store it on the caller as "
            "CW_SERVICE_CLIENT_SECRET\n"
        )
        return 0
    if args.action == "revoke":
        out.write(json.dumps(_describe(RevokeServiceClient(store).run(args.client_id))) + "\n")
        return 0
    for client in ListServiceClients(store).run():
        out.write(json.dumps(_describe(client)) + "\n")
    return 0


def _describe(client: ServiceClient) -> dict[str, object]:
    return {
        "client_id": client.client_id,
        "scopes": sorted(scope.value for scope in client.scopes),
        "created_at": client.created_at.isoformat(),
        "revoked_at": None if client.revoked_at is None else client.revoked_at.isoformat(),
    }


if __name__ == "__main__":
    raise SystemExit(main())
