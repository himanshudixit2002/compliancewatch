"""The release commands of the one deployable: ``cw-mvp migrate``, ``cw-mvp topics plan`` and
``apply``, ``cw-mvp release`` and ``cw-mvp check-config``.

``release`` is the step a deploy runs once per version, before the new app and worker start:
every service's migrations (``cw_mvp.migrate``), then the topics (``cw_mvp.topics``), and
nothing else. Both parts are idempotent, so running it again changes nothing. The topics are
applied only with ``CW_WORKER_KAFKA_ENABLED`` on: with the switch off nothing reads or writes
them, and a deployment without a broker still releases.

Each command prints what it did and returns the exit status: 0, or 1 with the reason on stderr
(a refusal, a failed migration, a broker that refused a topic). A configuration the settings
classes refuse is reported the way ``check-config`` reports it.
"""

import asyncio
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from pydantic import ValidationError

from cw_mvp.check_config import SHARED, check, refusals
from cw_mvp.migrate import MigrationFailedError, MigrationRefusedError, migrate, summary
from cw_mvp.settings import ReleaseSettings
from cw_mvp.topics import (
    TOPICS_FILE,
    KafkaTopicAdmin,
    TopicAdmin,
    TopicsError,
    TopicsFileError,
    apply,
    load,
    make_plan,
)
from py_common.kafka import KafkaClientConfig
from py_common.logging import configure_logging

SERVICE_NAME: Final = "cw-mvp-release"
"""The service name of the release commands' log lines."""

AdminFactory = Callable[[KafkaClientConfig], TopicAdmin]


def _out(line: str) -> None:
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _err(line: str) -> None:
    sys.stderr.write(line + "\n")


def release_settings() -> ReleaseSettings | None:
    """The settings from the environment and ``.env``; None, with the refusal on stderr, when
    a settings class refuses them."""
    try:
        settings = ReleaseSettings(service_name=SERVICE_NAME)
    except ValidationError as error:
        _err("refused: the settings are not valid (cw-mvp check-config lists every problem):")
        for problem in refusals(SHARED, error):
            _err(problem.line())
        return None
    configure_logging(
        service_name=SERVICE_NAME, log_level=settings.log_level, json_output=settings.log_json
    )
    return settings


def run_migrate(settings: ReleaseSettings, services: Sequence[str] = ()) -> int:
    try:
        results = migrate(settings, services=services, report=_out)
    except (MigrationRefusedError, MigrationFailedError) as error:
        _err(f"migrate: {error}")
        return 1
    _out(summary(results))
    return 0


def run_topics(
    settings: ReleaseSettings,
    command: str,
    *,
    path: Path = TOPICS_FILE,
    admin_factory: AdminFactory = KafkaTopicAdmin,
) -> int:
    """``plan`` or ``apply`` the topics file against the broker of ``settings``."""
    try:
        wanted = load(path)
    except (OSError, TopicsFileError) as error:
        _err(f"topics: {path}: {error}")
        return 1
    _out(
        f"topics {command}: {len(wanted.topics)} topics in {path.name}, broker "
        f"{settings.kafka_bootstrap} ({settings.kafka_security_protocol})"
    )

    async def run() -> int:
        async with admin_factory(KafkaClientConfig.from_settings(settings)) as admin:
            if command == "apply":
                done = await apply(admin, wanted)
                applied = True
            else:
                done = await make_plan(admin, wanted)
                applied = False
        for line in done.lines(applied=applied):
            _out(line)
        _out(f"topics {command}: {done.summary(applied=applied)}")
        return 0

    try:
        return asyncio.run(run())
    except TopicsError as error:
        _err(f"topics {command}: {error}")
    except Exception as error:  # the broker unreachable, refused credentials, a timeout
        _err(f"topics {command}: {settings.kafka_bootstrap}: {type(error).__name__}: {error}")
    return 1


def run_release(
    settings: ReleaseSettings,
    *,
    path: Path = TOPICS_FILE,
    admin_factory: AdminFactory = KafkaTopicAdmin,
) -> int:
    """Migrate every service, then apply the topics: the deploy's release step."""
    _out("release: migrate")
    status = run_migrate(settings)
    if status != 0:
        return status
    if not settings.worker_kafka_enabled:
        _out(
            "release: topics skipped, CW_WORKER_KAFKA_ENABLED is off: nothing reads or writes them"
        )
        return 0
    _out("release: topics apply")
    status = run_topics(settings, "apply", path=path, admin_factory=admin_factory)
    if status == 0:
        _out("release: done")
    return status


def run_check_config() -> int:
    report = check()
    for line in report.lines():
        _out(line)
    return 0 if report.ok else 1
