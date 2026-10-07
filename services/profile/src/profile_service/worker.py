"""The profile worker: ``python -m profile_service.worker``, locally
``make worker SERVICE=profile``.

``components(settings)`` is what it runs (``py_common.runtime.WorkerComponents``), and what
``cw-mvp worker`` hosts: a consumer in group ``profile.erasure`` of ``tenant.deletion.requested``
(``py_common.erasure``). While the flag ``identity.tenant_erasure`` is off for the tenant it only
logs ``erasure.off``. On, it checks the event with identity (``CW_IDENTITY_URL``, the service's
client with ``erasure:verify``): one identity did not send for the tenant's open deletion request
is refused, audited and dead-lettered at once. Otherwise it deletes the tenant's profile on the
consumer's connection (``infrastructure.erasure.PostgresProfileEraser``: versions, attributes,
review tasks, nodes, idempotency keys and published events) and writes ``tenant.data.erased``
(service profile), its ``tenant.erased`` audit entry and the erased marker, which commit with the
``processed_event`` row. What it cannot process, identity unreachable included, goes to
``tenant.deletion.requested.profile.erasure.dlq`` after the retries.

The consumer writes through Postgres, so the worker needs ``CW_PROFILE_STORE=postgres``. The
outbox relay that publishes profile's events runs on its own (``make relay SERVICE=profile``),
or in ``cw-mvp worker``.
"""

from typing import Final

from profile_service import __version__
from profile_service.infrastructure.erasure import PostgresProfileEraser
from profile_service.settings import ProfileSettings
from py_common.erasure import (
    Enabled,
    ErasureVerifier,
    erasure_component,
    erasure_switch,
    verifier_from,
)
from py_common.runtime import WorkerComponents, run_worker_process

SERVICE: Final = "profile"
SERVICE_NAME: Final = "profile-worker"


def components(
    settings: ProfileSettings,
    *,
    enabled: Enabled | None = None,
    verifier: ErasureVerifier | None = None,
) -> WorkerComponents:
    """The erasure consumer; ``enabled`` replaces the flag and ``verifier`` identity (tests)."""
    if settings.profile_store != "postgres":
        raise ValueError("the profile worker needs CW_PROFILE_STORE=postgres")
    return WorkerComponents(
        consumers=(
            erasure_component(
                SERVICE,
                PostgresProfileEraser,
                enabled=enabled or erasure_switch(settings),
                verifier=verifier or verifier_from(settings),
            ),
        )
    )


def main() -> None:
    run_worker_process(ProfileSettings(service_name=SERVICE_NAME), components, version=__version__)


if __name__ == "__main__":
    main()
