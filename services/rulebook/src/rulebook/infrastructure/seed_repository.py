"""Write the seed calendar into the rule tables.

A rule is matched by ``rule_key``. The seed's own draft, its latest version not drafted from a
rule candidate, is updated in place while it is still a draft (the analyst has not reviewed it),
so re-running the seed after editing the YAML changes nothing else, even when a candidate's draft
sits beside it. Once the seed's version has left draft it is never modified, and the seed adds a
new draft version only when its content differs from the rule's latest version.
``seed_status`` is left out of that comparison: review sets it to reviewed while the file still
says needs_review, and that alone is not a change to the rule.

A draft drafted from a rule candidate that was rejected is closed (``intake.version_closed``):
the seed skips it as if it were not there, so it never freezes the rule, and a new version is
numbered past it. Otherwise a rule whose latest version an analyst edited through its review
task (an ``edited`` row in its decision audit), or drafted from a rule candidate (its
``candidate_id``), is the analyst's: the seed neither overwrites that version nor adds one after
it, and reports the rule in ``kept_edited``; so is a seed draft an analyst edited.

Each rule's row is locked (``SELECT ... FOR UPDATE``) before its versions are read, as drafting a
version from a rule candidate locks it, so a seed and a draft running at once never take one
version number: the second waits for the first and numbers past what it wrote. A rule the seed
creates is inserted with ``ON CONFLICT DO NOTHING``, so one a draft created meanwhile is used.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import Engine, create_engine, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from domain_kernel.status import RuleVersionStatus
from rulebook.domain.publication import DecisionAction
from rulebook.domain.seed import (
    SEED_CONTENT_KEYS,
    SeedCalendar,
    SeedOutcome,
    SeedRule,
    reviewed_content,
    seed_content,
)
from rulebook.infrastructure.knowledge_repository import closed_version
from rulebook.infrastructure.models import RuleRow, RuleVersionDecisionRow, RuleVersionRow

__all__ = ["SeedOutcome", "SqlAlchemySeedRepository"]


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
        kept: list[str] = []
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            for rule in calendar.rules:
                row = _locked_rule(session, rule.rule_key)
                if row is None:
                    created = session.execute(
                        insert(RuleRow)
                        .values(
                            id=uuid.uuid4(),
                            rule_key=rule.rule_key,
                            regulator=rule.regulator,
                            level=rule.level.value,
                            created_at=now,
                        )
                        .on_conflict_do_nothing()
                        .returning(RuleRow.id)
                    ).first()
                    if created is not None:
                        created_rules.append(rule.rule_key)
                    row = _locked_rule(session, rule.rule_key)
                    assert row is not None, "the rule was inserted, here or by another writer"
                versions = session.execute(
                    select(RuleVersionRow, closed_version().label("closed"))
                    .where(RuleVersionRow.rule_id == row.id)
                    .order_by(RuleVersionRow.version)
                ).all()
                number = 1 + (versions[-1][0].version if versions else 0)
                current = [version for version, closed in versions if not closed]
                own = next((v for v in reversed(current) if v.candidate_id is None), None)
                content = seed_content(rule)
                if not current:
                    session.add(_version(row, rule, number, content, now))
                    created_versions.append(f"{rule.rule_key}@{number}")
                elif own is not None and own.status == RuleVersionStatus.DRAFT.value:
                    if _edited(session, own):
                        kept.append(rule.rule_key)
                    elif _content_of(own) == content:
                        unchanged.append(rule.rule_key)
                    else:
                        for key, value in content.items():
                            setattr(own, key, value)
                        updated.append(f"{rule.rule_key}@{own.version}")
                elif current[-1].candidate_id is not None or _edited(session, current[-1]):
                    kept.append(rule.rule_key)
                elif reviewed_content(_content_of(current[-1])) == reviewed_content(content):
                    unchanged.append(rule.rule_key)
                else:
                    session.add(_version(row, rule, number, content, now))
                    created_versions.append(f"{rule.rule_key}@{number}")
        return SeedOutcome(
            tuple(created_rules),
            tuple(created_versions),
            tuple(updated),
            tuple(unchanged),
            tuple(kept),
        )

    def ping(self) -> bool:
        with self._engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True


def _locked_rule(session: Session, rule_key: str) -> RuleRow | None:
    """The rule, locked for the rest of the seed's transaction as drafting a version from a rule
    candidate locks it (``lock_rule``), so the two never number a version alike."""
    return session.scalars(
        select(RuleRow).where(RuleRow.rule_key == rule_key).with_for_update()
    ).first()


def _edited(session: Session, row: RuleVersionRow) -> bool:
    """Whether an analyst edited the version through its review task."""
    found = session.scalar(
        select(RuleVersionDecisionRow.id)
        .where(
            RuleVersionDecisionRow.rule_version_id == row.id,
            RuleVersionDecisionRow.action == DecisionAction.EDITED.value,
        )
        .limit(1)
    )
    return found is not None


def _content_of(row: RuleVersionRow) -> dict[str, object]:
    return {key: getattr(row, key) for key in SEED_CONTENT_KEYS}


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
