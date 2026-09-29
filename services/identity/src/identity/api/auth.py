"""Sign-in, service tokens and the public keys: the routes that hand out access tokens.

- ``POST /sessions`` exchanges an identity provider token for an access token. A subject that
  signs in as nobody yet is a 404 identity-user-not-provisioned, which the web treats as sign-up.
- ``POST /service-tokens`` exchanges a service client's id and secret for a service token.
- ``GET /.well-known/jwks.json`` publishes the public keys every service verifies tokens with.
- ``GET /me`` answers the signed-in user, their tenant, roles, session version and whether they
  signed in with a second factor, after checking the session version against the store.
- ``POST /dev/provider-tokens`` signs a fake provider token for a phone number or an email
  address. It answers only with ``CW_AUTH_PROVIDER=fake`` in local and test, and 404 otherwise.

None of these but ``/me`` reads a bearer token: they are how a caller gets one.
"""

from fastapi import APIRouter, Response

from identity.api.deps import SignedInUser, Tenant, Wired
from identity.api.schemas import (
    DevProviderTokenIn,
    DevProviderTokenOut,
    JwkOut,
    JwksOut,
    MeOut,
    ServiceTokenIn,
    ServiceTokenOut,
    SessionIn,
    SessionOut,
)
from identity.domain.errors import DevSignInUnavailableError
from py_common.problems import problem_responses

JWKS_CACHE_CONTROL = "public, max-age=300"

router = APIRouter(prefix="/v1/identity", tags=["identity"])


@router.post(
    "/sessions",
    summary="Exchange an identity provider token for an access token",
    responses=problem_responses(401, 403, 404, 422, 503),
)
def exchange_session(body: SessionIn, wired: Wired) -> SessionOut:
    return SessionOut.from_session(wired.exchange_session.run(body.provider_token))


@router.post(
    "/service-tokens",
    summary="Exchange a service client's id and secret for a service token",
    responses=problem_responses(401, 422),
)
def issue_service_token(body: ServiceTokenIn, wired: Wired) -> ServiceTokenOut:
    session = wired.issue_service_token.run(body.client_id, body.client_secret)
    return ServiceTokenOut.from_session(session)


@router.get(
    "/.well-known/jwks.json",
    summary="The public keys access tokens are signed with (RFC 7517)",
)
def jwks(wired: Wired, response: Response) -> JwksOut:
    response.headers["Cache-Control"] = JWKS_CACHE_CONTROL
    return JwksOut(keys=[JwkOut(**key) for key in wired.keys.public_jwks()["keys"]])


@router.get(
    "/me",
    summary="The signed-in user: tenant, roles, session version and second factor",
    responses=problem_responses(401, 403),
)
def me(tenant: Tenant, principal: SignedInUser, wired: Wired) -> MeOut:
    current_tenant, user = wired.current_user.run(principal)
    return MeOut.from_session(principal, current_tenant, user)


@router.post(
    "/dev/provider-tokens",
    summary="Sign a fake provider token (fake provider, local and test only)",
    responses=problem_responses(404, 422),
)
def dev_provider_token(body: DevProviderTokenIn, wired: Wired) -> DevProviderTokenOut:
    fake = wired.dev_provider
    if fake is None:
        raise DevSignInUnavailableError()
    token = fake.issue(email=body.email or "", phone=body.phone or "", aal=body.aal)
    return DevProviderTokenOut(provider_token=token, subject=fake.verify(token).subject)
