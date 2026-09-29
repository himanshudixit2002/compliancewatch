"""Write the seed calendar into the rule tables.

A rule is matched by ``rule_key``. Its latest version is updated in place while it is still a
draft (the analyst has not reviewed it), so re-running the seed after editing the YAML changes
nothing else; once a version has left draft it is never modified and the seed adds a new draft
version only when its content differs from the latest one. ``seed_status`` is left out of that
comparison: review sets it to reviewed while the file still says needs_review, and that alone is
not a change to the rule.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.predicates import specification_to_mapping
from domain_kernel.status import RuleVersionStatus
from rulebook.domain.seed import SeedCalendar, SeedRule
from rulebook.infrastructure.models import RuleRow, RuleVersionRow


@dataclass(frozen=True, slots=True)
class SeedOutcome:
    created_rules: tuple[str, ...] = ()
    created_versions: tuple[str, ...] = ()
    updated_drafts: tuple[str, ...] = ()
    unchanged: tuple[str, ...] = ()
    problems: tuple[str, ...] = field(default_factory=tuple)

    @property
    def summary(self) -> str:
        return (
            f"{len(self.created_rules)} new rules, {len(self.created_versions)} new versions, "
            f"{len(self.updated_drafts)} drafts updated, {len(self.unchanged)} unchanged"
        )


class SqlAlchemySeedRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @classmethod
    def from_url(cls, database_url: str) -> "SqlAlchemySeedRepository":
        return cls(create_engine(database_url, poolclass=NullPool))

    def apply(self, calendar: SeedCalendar, *, now: datetime | None = None) -> SeedOutcome:
        now = now or datetime.now(UTC)
        created_rules: list[str] = []
        created_versions: list[str] = []
        updated: list[str] = []
        unchanged: list[str] = []
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            for rule in calendar.rules:
                row = session.scalars(
                    select(RuleRow).where(RuleRow.rule_key == rule.rule_key)
                ).first()
                if row is None:
                    row = RuleRow(
                        id=uuid.uuid4(),
                        rule_key=rule.rule_key,
                        regulator=rule.regulator,
                        level=rule.level.value,
                        created_at=now,
                    )
                    session.add(row)
                    session.flush()
                    created_rules.append(rule.rule_key)
                latest = session.scalars(
                    select(RuleVersionRow)
                    .where(RuleVersionRow.rule_id == row.id)
                    .order_by(RuleVersionRow.version.desc())
                ).first()
                content = _content(rule)
                if latest is None:
                    session.add(_version(row, rule, 1, content, now))
                    created_versions.append(f"{rule.rule_key}@1")
                elif latest.status == RuleVersionStatus.DRAFT.value:
                    if _content_of(latest) == content:
                        unchanged.append(rule.rule_key)
                    else:
                        for key, value in content.items():
                            setattr(latest, key, value)
                        updated.append(f"{rule.rule_key}@{latest.version}")
                elif _reviewed(_content_of(latest)) == _reviewed(content):
                    unchanged.append(rule.rule_key)
                else:
                    session.add(_version(row, rule, latest.version + 1, content, now))
                    created_versions.append(f"{rule.rule_key}@{latest.version + 1}")
        return SeedOutcome(
            tuple(created_rules), tuple(created_versions), tuple(updated), tuple(unchanged)
        )

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


CONTENT_KEYS = (
    "title",
    "summary",
    "specification",
    "obligation_template",
    "recurrence",
    "effective_from",
    "source",
    "seed_status",
    "todo",
)


def _content(rule: SeedRule) -> dict[str, object]:
    return {
        "title": rule.title,
        "summary": rule.summary,
        "specification": specification_to_mapping(rule.specification),
        "obligation_template": rule.obligation_template.to_mapping(),
        "recurrence": None if rule.recurrence is None else rule.recurrence.to_mapping(),
        "effective_from": rule.effective_from,
        "source": rule.source.to_mapping(),
        "seed_status": rule.seed_status.value,
        "todo": list(rule.todo),
    }


def _content_of(row: RuleVersionRow) -> dict[str, object]:
    return {key: getattr(row, key) for key in CONTENT_KEYS}


def _reviewed(content: dict[str, object]) -> dict[str, object]:
    """The content a version past draft is compared on: everything but ``seed_status``."""
    return {key: value for key, value in content.items() if key != "seed_status"}


def _version(
    rule_row: RuleRow, rule: SeedRule, version: int, content: dict[str, object], now: datetime
) -> RuleVersionRow:
    return RuleVersionRow(
        id=uuid.uuid4(),
        rule_id=rule_row.id,
        version=version,
        status=RuleVersionStatus.DRAFT.value,
        created_at=now,
        **content,
    )
