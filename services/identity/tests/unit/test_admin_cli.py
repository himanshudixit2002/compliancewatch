"""``identity-admin``: signing keys, and service clients whose secret is shown once."""

import io
import json

import pytest

from identity.admin import main
from identity.domain.service_clients import secret_digest
from identity.infrastructure.memory import MemoryStore
from py_common.auth import load_signing_keys


def run(store: MemoryStore, *argv: str) -> tuple[int, str]:
    out = io.StringIO()
    code = main(list(argv), unit_of_work=store, out=out)
    return code, out.getvalue()


def test_signing_key_new_prints_a_key_set_the_service_loads() -> None:
    out = io.StringIO()
    assert main(["signing-key", "new", "--kid", "2026-10"], out=out) == 0
    keys = load_signing_keys(out.getvalue())
    assert keys.signing_key.kid == "2026-10"
    assert "PRIVATE KEY" in json.loads(out.getvalue())[0]["pem"]
    assert main(["signing-key", "new", "--kid", " spaced "], out=io.StringIO()) == 1


def test_service_client_create_prints_the_secret_once_and_stores_its_digest(
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = MemoryStore()
    code, printed = run(
        store, "service-client", "create", "--id", "pipeline", "--scope", "rulebook:write"
    )
    assert code == 0
    created = json.loads(printed)
    secret = created["client_secret"]
    assert (created["client_id"], created["scopes"], created["revoked_at"]) == (
        "pipeline",
        ["rulebook:write"],
        None,
    )
    assert store.service_clients["pipeline"].secret_sha256 == secret_digest(secret)
    assert secret not in repr(store.service_clients)
    assert "shown once" in capsys.readouterr().err
    code, listed = run(store, "service-client", "list")
    assert code == 0
    assert secret not in listed
    assert json.loads(listed)["client_id"] == "pipeline"
    code, _ = run(store, "service-client", "create", "--id", "pipeline")
    assert code == 1
    assert "exists" in capsys.readouterr().err


def test_service_client_revoke(capsys: pytest.CaptureFixture[str]) -> None:
    store = MemoryStore()
    run(store, "service-client", "create", "--id", "qa", "--scope", "llm:call")
    code, printed = run(store, "service-client", "revoke", "--id", "qa")
    assert code == 0
    assert json.loads(printed)["revoked_at"] is not None
    assert store.service_clients["qa"].revoked_at is not None
    assert run(store, "service-client", "revoke", "--id", "nobody")[0] == 1
    assert "no service client nobody" in capsys.readouterr().err


def test_a_bad_client_id_or_scope_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    store = MemoryStore()
    assert run(store, "service-client", "create", "--id", "Bad Id")[0] == 1
    assert "client id" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        run(store, "service-client", "create", "--id", "qa", "--scope", "admin")
    assert store.service_clients == {}
