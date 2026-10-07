"""``identity-admin``: what an operator runs against the identity service's keys and store.

::

    identity-admin signing-key new --kid 2026-10
    identity-admin service-client create --id pipeline --scope rulebook:write --scope llm:call
    identity-admin service-client revoke --id pipeline
    identity-admin service-client list
    identity-admin bootstrap-internal --name "Regulatory team" --email admin@example.org
    identity-admin audit-export --from 2026-09-01 --to 2026-10-01 --out var/audit-export/2026-09

``signing-key new`` prints a key set with one new ES256 key, the JSON ``CW_IDENTITY_SIGNING_KEYS``
takes; it touches no store. To rotate, put the new record second in the environment's key set,
wait longer than verifiers cache keys (an hour), then move it to the front and drop the old one
once no token it signed is still alive.

``service-client create`` prints the client and its secret as JSON, once: store the secret on the
caller as ``CW_SERVICE_CLIENT_SECRET``; the store keeps only its SHA-256. ``revoke`` stops new
tokens at once; tokens already issued expire within the token lifetime. ``list`` shows ids,
scopes and dates, never a secret.

``bootstrap-internal`` creates the internal tenant, where the regulatory team works, with its first
admin, whose account it creates at the identity provider (``CW_AUTH_PROVIDER``). There is one
internal tenant; a second run is refused. The admin enrols a second factor at the provider before
signing in, and then invites the analysts and reviewers.

``audit-export`` writes every audit entry from ``--from`` (inclusive) to ``--to`` (exclusive),
oldest first, to ``audit-events.ndjson`` in ``--out`` (made when missing; a directory holding an
export already is refused), and ``manifest.json`` beside it: the file's SHA-256, the count, the
range and when it was generated. A date without a time is midnight UTC. It reads under the export
scope (``app.audit_scope = 'export'``), so it sees every tenant's rows and the platform's, and it
records itself as an ``audit.exported`` entry. Uploading the two files to the object-locked
bucket is a manual step (docs/runbooks/audit-export.md).

Every command but ``signing-key`` uses the database at ``CW_DATABASE_URL``, whose search_path
must name the identity schema, as ``make migrate`` sets it, and the service-client, bootstrap and
export commands write their audit entries as ``system:identity-admin``.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import TextIO

from domain_kernel.access import Scope
from domain_kernel.errors import DomainError
from identity.application.audit import ExportAuditTrail
from identity.application.bootstrap import (
    BootstrapInternalTenant,
    CreateServiceClient,
    ListServiceClients,
    RevokeServiceClient,
)
from identity.composition import identity_provider
from identity.domain.audit import AuditReader
from identity.domain.provider import IdentityProvider
from identity.domain.repository import UnitOfWorkFactory
from identity.domain.service_clients import ServiceClient
from identity.domain.tenancy import Contact
from identity.infrastructure.audit_reader import PostgresAuditReader
from identity.infrastructure.repository import PostgresUnitOfWorkFactory
from identity.settings import IdentitySettings
from py_common.auth import KeySet, generate_signing_key

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

    bootstrap = commands.add_parser(
        "bootstrap-internal", help="create the internal tenant and its first admin"
    )
    bootstrap.add_argument("--name", required=True, help="the internal tenant's name")
    bootstrap.add_argument("--display-name", default="", help="the admin's name")
    contact = bootstrap.add_mutually_exclusive_group(required=True)
    contact.add_argument("--email", help="the admin's email address")
    contact.add_argument("--phone", help="the admin's phone number, E.164")

    export = commands.add_parser(
        "audit-export", help="write the audit entries of a range as NDJSON with a manifest"
    )
    export.add_argument(
        "--from", required=True, dest="since", type=instant, help="inclusive: 2026-09-01"
    )
    export.add_argument(
        "--to", required=True, dest="until", type=instant, help="exclusive: 2026-10-01"
    )
    export.add_argument("--out", required=True, type=Path, help="the directory to write")
    return root


def instant(text: str) -> datetime:
    """An ISO date (midnight UTC) or an ISO instant; one without a zone is UTC."""
    try:
        if len(text) == len("2026-09-01"):
            day = date.fromisoformat(text)
            return datetime(day.year, day.month, day.day, tzinfo=UTC)
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO date or instant: {text!r}") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def main(
    argv: Sequence[str] | None = None,
    *,
    unit_of_work: UnitOfWorkFactory | None = None,
    provider: IdentityProvider | None = None,
    reader: AuditReader | None = None,
    out: TextIO | None = None,
) -> int:
    """Run one command. ``unit_of_work``, ``provider`` and ``reader`` replace the ones the
    settings name (tests)."""
    args = parser().parse_args(argv)
    stream = out or sys.stdout
    try:
        if args.command == "signing-key":
            return _new_signing_key(args.kid, stream)
        if args.command == "audit-export":
            return _audit_export(args, unit_of_work, reader, stream)
        if unit_of_work is None or provider is None:
            settings = IdentitySettings(service_name=PROG)
            store = unit_of_work or PostgresUnitOfWorkFactory.from_url(settings.database_url)
            chosen = provider or identity_provider(settings)
        else:
            store, chosen = unit_of_work, provider
        if args.command == "bootstrap-internal":
            return _bootstrap(args, store, chosen, stream)
        return _service_client(args, store, stream)
    except (DomainError, ValueError) as exc:
        sys.stderr.write(f"{PROG}: {exc}\n")
        return 1


def _bootstrap(
    args: argparse.Namespace, store: UnitOfWorkFactory, provider: IdentityProvider, out: TextIO
) -> int:
    contact = Contact.of(email=args.email, phone=args.phone)
    tenant, admin = BootstrapInternalTenant(store, provider).run(
        args.name, contact, display_name=args.display_name
    )
    described = {
        "tenant_id": str(tenant.id),
        "tenant_name": tenant.name,
        "admin_user_id": str(admin.id),
        "admin_email": admin.contact.email,
        "admin_phone": admin.contact.phone,
    }
    out.write(json.dumps(described, indent=2) + "\n")
    sys.stderr.write(
        f"{PROG}: the admin enrols a second factor at the identity provider, then signs in\n"
    )
    return 0


def _audit_export(
    args: argparse.Namespace,
    unit_of_work: UnitOfWorkFactory | None,
    reader: AuditReader | None,
    out: TextIO,
) -> int:
    if unit_of_work is None or reader is None:
        postgres = PostgresUnitOfWorkFactory.from_url(
            IdentitySettings(service_name=PROG).database_url
        )
        unit_of_work, reader = postgres, PostgresAuditReader(postgres.engine)
    manifest = ExportAuditTrail(reader, unit_of_work).run(args.since, args.until, args.out)
    out.write(json.dumps(manifest.document(), indent=2, sort_keys=True) + "\n")
    sys.stderr.write(
        f"{PROG}: upload {args.out / manifest.file} and its manifest.json to the object-locked "
        "bucket (docs/runbooks/audit-export.md)\n"
    )
    return 0


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
