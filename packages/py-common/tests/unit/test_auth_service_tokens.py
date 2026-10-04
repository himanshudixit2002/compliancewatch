import json
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import SecretStr

from domain_kernel.access import Principal, Role, Scope
from domain_kernel.ids import TenantId, UserId
from py_common.auth import (
    BearerAuth,
    IssuerTokenSource,
    ServiceTokenSource,
    ServiceTokenUnavailableError,
    TokenIssuer,
    service_auth_from,
)
from py_common.auth.service_tokens import SERVICE_TOKENS_PATH, service_client_id, token_refused
from py_common.auth.testing import TestIssuer
from py_common.settings import Settings

_IDENTITY = "http://identity.test"
_TARGET = "http://rulebook.test/v1/rulebook/documents"
_CLIENT_SECRET = SecretStr("client-" + "c" * 32)
"""The demo client secret these tests exchange; the fake identity checks it."""


class _Identity:
    """The identity service's token route, for MockTransport: counts exchanges and numbers the
    tokens it issues."""

    def __init__(self, expires_in: object = 600) -> None:
        self.expires_in = expires_in
        self.issued = 0
        self.requests: list[dict[str, Any]] = []
        self.answer: Callable[[], httpx2.Response] | None = None

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == _IDENTITY + SERVICE_TOKENS_PATH
        assert request.method == "POST"
        self.requests.append(json.loads(request.content))
        if self.answer is not None:
            return self.answer()
        self.issued += 1
        return httpx2.Response(
            200,
            json={
                "access_token": f"token-{self.issued}",
                "token_type": "Bearer",
                "expires_in": self.expires_in,
                "scopes": ["rulebook:write"],
            },
        )


class _Clock:
    def __init__(self) -> None:
        self.now = 50.0

    def __call__(self) -> float:
        return self.now


def _source(identity: _Identity, clock: _Clock | None = None) -> ServiceTokenSource:
    return ServiceTokenSource(
        _IDENTITY + "/",
        "pipeline",
        _CLIENT_SECRET,
        client=httpx2.Client(transport=httpx2.MockTransport(identity)),
        clock=clock or _Clock(),
    )


def test_the_token_is_cached_until_a_minute_before_it_expires() -> None:
    identity, clock = _Identity(expires_in=600), _Clock()
    source = _source(identity, clock)
    assert source.client_id == "pipeline"
    assert source.token() == "token-1"
    assert identity.requests == [
        {"client_id": "pipeline", "client_secret": _CLIENT_SECRET.get_secret_value()}
    ]
    clock.now += 539
    assert source.token() == "token-1"
    assert identity.issued == 1
    clock.now += 1
    assert source.token() == "token-2"
    assert identity.issued == 2


def test_a_short_lived_token_is_refreshed_at_half_its_lifetime() -> None:
    identity, clock = _Identity(expires_in=60), _Clock()
    source = _source(identity, clock)
    assert source.token() == "token-1"
    clock.now += 29
    assert source.token() == "token-1"
    clock.now += 1
    assert source.token() == "token-2"


def test_invalidate_drops_only_the_cached_token() -> None:
    identity = _Identity()
    source = _source(identity)
    first = source.token()
    source.invalidate("some other token")
    assert source.token() == first
    source.invalidate(first)
    assert source.token() == "token-2"


def test_concurrent_callers_share_one_exchange() -> None:
    identity = _Identity()
    source = _source(identity)
    seen: list[str] = []
    threads = [threading.Thread(target=lambda: seen.append(source.token())) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert seen == ["token-1"] * 8
    assert identity.issued == 1


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (
            lambda: httpx2.Response(
                401, json={"type": "urn:compliancewatch:problem:identity-service-client-invalid"}
            ),
            "401 urn:compliancewatch:problem:identity-service-client-invalid",
        ),
        (lambda: httpx2.Response(503, content=b"down"), "refused a token for client pipeline: 503"),
        (lambda: httpx2.Response(200, content=b"<html>"), "not JSON"),
        (lambda: httpx2.Response(200, json=["token"]), "lacks a bearer access_token"),
        (lambda: httpx2.Response(200, json={"access_token": "t"}), "lacks a bearer"),
        (
            lambda: httpx2.Response(200, json={"access_token": "t", "expires_in": 0}),
            "lacks a bearer",
        ),
        (
            lambda: httpx2.Response(200, json={"access_token": "t", "expires_in": True}),
            "lacks a bearer",
        ),
        (
            lambda: httpx2.Response(
                200, json={"access_token": "t", "expires_in": 600, "token_type": "mac"}
            ),
            "lacks a bearer",
        ),
    ],
)
def test_a_refusal_or_a_bad_answer_is_surfaced_as_an_error(
    answer: Callable[[], httpx2.Response], message: str
) -> None:
    identity = _Identity()
    identity.answer = answer
    with pytest.raises(ServiceTokenUnavailableError, match=message) as raised:
        _source(identity).token()
    assert _CLIENT_SECRET.get_secret_value() not in str(raised.value)


def test_an_unreachable_identity_is_surfaced_as_an_error() -> None:
    def down(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    source = ServiceTokenSource(
        _IDENTITY,
        "pipeline",
        _CLIENT_SECRET,
        client=httpx2.Client(transport=httpx2.MockTransport(down)),
    )
    with pytest.raises(ServiceTokenUnavailableError, match=r"could not be reached.*ConnectError"):
        source.token()


def test_a_failed_fetch_is_tried_again_after_a_few_seconds() -> None:
    identity, clock = _Identity(), _Clock()
    source = _source(identity, clock)
    source.token()
    clock.now += 600
    identity.answer = lambda: httpx2.Response(503)
    with pytest.raises(ServiceTokenUnavailableError, match="503"):
        source.token()
    identity.answer = None
    clock.now += 4
    with pytest.raises(ServiceTokenUnavailableError, match="next attempt is in 1 s"):
        source.token()
    assert len(identity.requests) == 2, "no call waits on identity until the next attempt"
    clock.now += 1
    assert source.token() == "token-2"


def test_a_failed_refresh_keeps_the_token_until_it_expires() -> None:
    identity, clock = _Identity(expires_in=600), _Clock()
    source = _source(identity, clock)
    assert source.token() == "token-1"
    clock.now += 545
    identity.answer = lambda: httpx2.Response(503)
    assert source.token() == "token-1", "55 seconds of validity are left"
    assert len(identity.requests) == 2
    clock.now += 4
    assert source.token() == "token-1"
    assert len(identity.requests) == 2, "the next attempt waits five seconds"
    clock.now += 1
    assert source.token() == "token-1"
    assert len(identity.requests) == 3
    clock.now += 50
    with pytest.raises(ServiceTokenUnavailableError, match="503"):
        source.token()
    identity.answer = None
    clock.now += 5
    assert source.token() == "token-2"


def test_a_source_needs_a_client_id() -> None:
    with pytest.raises(ValueError, match="client id"):
        ServiceTokenSource(_IDENTITY, " ", _CLIENT_SECRET)


# ---------------------------------------------------------------- BearerAuth


_TOKEN_INVALID = "urn:compliancewatch:problem:auth-token-invalid"
_WRITE_TOKEN_INVALID = "urn:compliancewatch:problem:write-token-invalid"


class _Rulebook:
    """A called service that records the Authorization header and refuses the tokens it is told
    to, as ``py_common.auth`` does: 401 ``auth-token-invalid`` with an ``invalid_token``
    challenge. ``other`` is a 401 about something else that it answers instead."""

    def __init__(self) -> None:
        self.seen: list[tuple[str | None, bytes]] = []
        self.refuse: set[str] = set()
        self.other: httpx2.Response | None = None

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        authorization = request.headers.get("authorization")
        self.seen.append((authorization, request.content))
        if self.other is not None:
            return self.other
        if authorization in self.refuse:
            return httpx2.Response(
                401,
                json={"type": _TOKEN_INVALID},
                headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
            )
        return httpx2.Response(200, json={"ok": True})


def test_bearer_auth_sends_the_token_on_every_request() -> None:
    identity, rulebook = _Identity(), _Rulebook()
    auth = BearerAuth(_source(identity))
    with httpx2.Client(transport=httpx2.MockTransport(rulebook), auth=auth) as client:
        assert client.put(_TARGET, json={"a": 1}).status_code == 200
        assert client.get(_TARGET).status_code == 200
    assert [authorization for authorization, _ in rulebook.seen] == ["Bearer token-1"] * 2
    assert identity.issued == 1


def test_a_401_refreshes_the_token_and_resends_the_request_once() -> None:
    identity, rulebook = _Identity(), _Rulebook()
    rulebook.refuse = {"Bearer token-1"}
    with httpx2.Client(
        transport=httpx2.MockTransport(rulebook), auth=BearerAuth(_source(identity))
    ) as client:
        response = client.put(_TARGET, json={"document": "d1"})
    assert response.status_code == 200
    assert [authorization for authorization, _ in rulebook.seen] == [
        "Bearer token-1",
        "Bearer token-2",
    ]
    assert rulebook.seen[0][1] == rulebook.seen[1][1] == b'{"document":"d1"}'


@pytest.mark.parametrize(
    "refusal",
    [
        httpx2.Response(401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'}),
        httpx2.Response(
            401, headers={"www-authenticate": 'bearer realm="cw", error=invalid_token'}
        ),
        httpx2.Response(401, json={"type": _TOKEN_INVALID}),
        httpx2.Response(401, json={"type": "auth-token-invalid"}),
    ],
)
def test_token_refusals_are_told_by_their_challenge_or_problem_type(
    refusal: httpx2.Response,
) -> None:
    assert token_refused(refusal)


@pytest.mark.parametrize(
    "other",
    [
        httpx2.Response(401, json={"type": _WRITE_TOKEN_INVALID}),
        httpx2.Response(
            401,
            json={"type": "urn:compliancewatch:problem:auth-token-required"},
            headers={"WWW-Authenticate": "Bearer"},
        ),
        httpx2.Response(401, content=b"no"),
        httpx2.Response(403, json={"type": _TOKEN_INVALID}),
    ],
)
def test_other_answers_are_not_token_refusals(other: httpx2.Response) -> None:
    assert not token_refused(other)


def test_a_401_about_something_else_is_returned_without_a_new_token() -> None:
    identity, rulebook = _Identity(), _Rulebook()
    rulebook.other = httpx2.Response(401, json={"type": _WRITE_TOKEN_INVALID})
    with httpx2.Client(
        transport=httpx2.MockTransport(rulebook), auth=BearerAuth(_source(identity))
    ) as client:
        response = client.put(_TARGET, json={"document": "d1"})
    assert response.status_code == 401
    assert response.json()["type"] == _WRITE_TOKEN_INVALID
    assert len(rulebook.seen) == 1
    assert identity.issued == 1


async def test_an_async_401_about_something_else_is_returned_as_it_came() -> None:
    identity, rulebook = _Identity(), _Rulebook()
    rulebook.other = httpx2.Response(401, json={"type": _WRITE_TOKEN_INVALID})
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(rulebook), auth=BearerAuth(_source(identity))
    ) as client:
        response = await client.get(_TARGET)
    assert (response.status_code, len(rulebook.seen), identity.issued) == (401, 1, 1)


def test_a_second_401_is_returned_to_the_caller() -> None:
    identity, rulebook = _Identity(), _Rulebook()
    rulebook.refuse = {"Bearer token-1", "Bearer token-2"}
    with httpx2.Client(
        transport=httpx2.MockTransport(rulebook), auth=BearerAuth(_source(identity))
    ) as client:
        assert client.get(_TARGET).status_code == 401
    assert len(rulebook.seen) == 2


def test_a_token_failure_surfaces_from_the_call() -> None:
    identity = _Identity()
    identity.answer = lambda: httpx2.Response(401)
    with (
        httpx2.Client(
            transport=httpx2.MockTransport(_Rulebook()), auth=BearerAuth(_source(identity))
        ) as client,
        pytest.raises(ServiceTokenUnavailableError),
    ):
        client.get(_TARGET)


async def test_bearer_auth_works_for_async_clients() -> None:
    identity, rulebook = _Identity(), _Rulebook()
    rulebook.refuse = {"Bearer token-1"}
    auth = BearerAuth(_source(identity))
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(rulebook), auth=auth) as client:
        first = await client.post(_TARGET, json={"x": 1})
        second = await client.get(_TARGET)
    assert (first.status_code, second.status_code) == (200, 200)
    assert [authorization for authorization, _ in rulebook.seen] == [
        "Bearer token-1",
        "Bearer token-2",
        "Bearer token-2",
    ]


# ---------------------------------------------------------------- service_auth_from


def _settings(**values: Any) -> Settings:
    return Settings(_env_file=None, identity_url=_IDENTITY, **values)


def test_no_secret_means_no_token_is_sent() -> None:
    assert service_auth_from(_settings()) is None
    assert service_auth_from(_settings(service_client_id="qa")) is None
    assert service_auth_from(_settings(service_client_id="qa", service_client_secret="")) is None


def test_without_a_client_id_the_service_name_is_the_client() -> None:
    settings = _settings(service_name="qa", service_client_secret=_CLIENT_SECRET)
    assert settings.service_client_id == ""
    auth = service_auth_from(settings)
    assert auth is not None
    assert auth.source.client_id == "qa"
    named = _settings(
        service_name="pipeline-worker",
        service_client_id=" pipeline ",
        service_client_secret=_CLIENT_SECRET,
    )
    assert service_client_id(named) == "pipeline"


def test_a_secret_without_a_client_id_starts_every_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A shared .env with the dev secret and no id, as .env.example suggests, is read by make
    targets that set no id (migrate, relay, seed)."""
    secret = _CLIENT_SECRET.get_secret_value()
    (tmp_path / ".env").write_text(
        f"CW_SERVICE_CLIENT_ID=\nCW_SERVICE_CLIENT_SECRET={secret}\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    settings = Settings(service_name="rulebook")
    assert settings.service_client_secret is not None
    assert service_client_id(settings) == "rulebook"


def test_clients_built_from_the_same_settings_share_one_token_source() -> None:
    settings = _settings(service_client_id="qa", service_client_secret=_CLIENT_SECRET)
    first, second = service_auth_from(settings), service_auth_from(settings)
    assert isinstance(first, BearerAuth)
    assert isinstance(second, BearerAuth)
    assert first.source is second.source
    assert first.source.client_id == "qa"
    other = service_auth_from(
        _settings(service_client_id="pipeline", service_client_secret=_CLIENT_SECRET)
    )
    assert other is not None
    assert other.source is not first.source


def test_an_injected_client_gets_its_own_source() -> None:
    identity, rulebook = _Identity(), _Rulebook()
    settings = _settings(service_client_id="pipeline", service_client_secret=_CLIENT_SECRET)
    auth = service_auth_from(
        settings, client=httpx2.Client(transport=httpx2.MockTransport(identity))
    )
    assert auth is not None
    assert auth.source is not service_auth_from(settings).source  # type: ignore[union-attr]
    with httpx2.Client(transport=httpx2.MockTransport(rulebook), auth=auth) as client:
        client.get(_TARGET)
    assert rulebook.seen[0][0] == "Bearer token-1"
    assert identity.requests[0]["client_id"] == "pipeline"


def _minter(clock: _Clock) -> tuple[TestIssuer, IssuerTokenSource]:
    issuer = TestIssuer()
    principal = Principal.service("qa", [Scope.TENANT_ACT, Scope.LLM_CALL])
    return issuer, IssuerTokenSource(
        TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience),
        principal,
        clock=clock,
    )


def test_an_in_process_source_mints_verifiable_service_tokens_and_keeps_them() -> None:
    clock = _Clock()
    issuer, source = _minter(clock)
    assert source.client_id == "qa"
    first = source.token()
    principal = issuer.verifier().verify(first)
    assert principal.subject == "qa"
    assert principal.scopes == frozenset({Scope.TENANT_ACT, Scope.LLM_CALL})
    clock.now += 539
    assert source.token() == first, "kept until a minute before it expires"
    clock.now += 1
    second = source.token()
    assert second != first
    source.invalidate("not-the-cached-token")
    assert source.token() == second
    source.invalidate(second)
    assert source.token() != second


def test_an_in_process_source_mints_for_services_only() -> None:
    issuer = TestIssuer()
    minting = TokenIssuer(issuer.keys, issuer=issuer.issuer_name, audience=issuer.audience)
    person = Principal.user(UserId.new(), TenantId.new(), [Role.OWNER])
    with pytest.raises(ValueError, match="service tokens only"):
        IssuerTokenSource(minting, person)
    with pytest.raises(ValueError, match="ttl"):
        IssuerTokenSource(minting, Principal.service("qa", []), ttl=timedelta(0))


def test_a_token_source_of_the_callers_is_used_without_a_secret() -> None:
    _, source = _minter(_Clock())
    auth = service_auth_from(_settings(), token_source=source)
    assert isinstance(auth, BearerAuth)
    assert auth.source is source
    rulebook = _Rulebook()
    with httpx2.Client(transport=httpx2.MockTransport(rulebook), auth=auth) as client:
        client.get(_TARGET)
    assert rulebook.seen[0][0] == f"Bearer {source.token()}"
    with_secret = _settings(service_client_id="qa", service_client_secret=_CLIENT_SECRET)
    chosen = service_auth_from(with_secret, token_source=source)
    assert chosen is not None
    assert chosen.source is source, "the caller's source wins over the client secret"
