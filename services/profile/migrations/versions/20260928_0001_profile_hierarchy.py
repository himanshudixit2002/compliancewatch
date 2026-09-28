"""profile hierarchy: nodes, attribute values, version history, review tasks, all with row-level
security by tenant; plus the outbox and consumer inbox tables

Revision ID: 0001
Revises:
Create Date: 2026-09-28

Hand-written; mirrors profile_service.infrastructure.models. Every tenant table has
tenant_id NOT NULL and a forced row-level security policy reading the app.tenant_id setting
(NULLIF against '' because a used custom setting reads as an empty string between
transactions). Table names are unqualified and land in the schema at the front of search_path.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from py_common.outbox import (
    create_outbox_table,
    create_processed_event_table,
    drop_outbox_table,
    drop_processed_event_table,
)

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

LEVELS = ("entity", "registration", "location")
STATES = ("known", "unsure", "not_applicable")
SOURCES = ("gstin_lookup", "user_input", "derived")
REASONS = ("not_applicable", "confirm_financial_year")
TENANT_TABLES = ("profile_node", "profile_attribute", "profile_version", "review_task")


def _in_list(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _enable_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_tenant_isolation ON {table} "
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )


def upgrade() -> None:
    op.create_table(
        "profile_node",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=80), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("parent_id", sa.Uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_profile_node"),
        sa.UniqueConstraint("tenant_id", "level", "key", name="uq_profile_node_key"),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["profile_node.id"], name="fk_profile_node_parent_id_profile_node"
        ),
        sa.CheckConstraint(_in_list("level", LEVELS), name="ck_profile_node_level"),
        sa.CheckConstraint(
            "(level = 'entity') = (parent_id IS NULL)", name="ck_profile_node_parent"
        ),
        comment="Hierarchy nodes: entity (PAN), registration (GSTIN), location. RLS by tenant_id.",
    )
    op.create_index("ix_profile_node_parent", "profile_node", ["parent_id"])
    op.create_table(
        "profile_attribute",
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("fy_label", sa.String(length=7), server_default="", nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("node_id", "key", "fy_label", name="pk_profile_attribute"),
        sa.ForeignKeyConstraint(
            ["node_id"], ["profile_node.id"], name="fk_profile_attribute_node_id_profile_node"
        ),
        sa.CheckConstraint(_in_list("state", STATES), name="ck_profile_attribute_state"),
        sa.CheckConstraint(_in_list("source", SOURCES), name="ck_profile_attribute_source"),
        sa.CheckConstraint(
            "(state = 'known') = (value IS NOT NULL)", name="ck_profile_attribute_value"
        ),
        comment=(
            "One value per node, attribute and financial year ('' when the attribute is not "
            "per year). value is the ontology's canonical form as JSON."
        ),
    )
    op.create_table(
        "profile_version",
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("changed_attributes", postgresql.JSONB(), nullable=False),
        sa.Column("attributes", postgresql.JSONB(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("changed_by", sa.Uuid(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("node_id", "version", name="pk_profile_version"),
        sa.ForeignKeyConstraint(
            ["node_id"], ["profile_node.id"], name="fk_profile_version_node_id_profile_node"
        ),
        comment="History: the attributes of a node after each change, for replay.",
    )
    op.create_table(
        "review_task",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("node_id", sa.Uuid(), nullable=False),
        sa.Column("attribute_key", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column("fy_label", sa.String(length=7), server_default="", nullable=False),
        sa.Column("open", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_review_task"),
        sa.ForeignKeyConstraint(
            ["node_id"], ["profile_node.id"], name="fk_review_task_node_id_profile_node"
        ),
        sa.CheckConstraint(_in_list("reason", REASONS), name="ck_review_task_reason"),
        comment="Questions for a person: not-applicable answers and financial-year confirmations.",
    )
    op.create_index("ix_review_task_open", "review_task", ["tenant_id", "open"])
    for table in TENANT_TABLES:
        _enable_rls(table)
    create_outbox_table(op)
    create_processed_event_table(op)


def downgrade() -> None:
    drop_processed_event_table(op)
    drop_outbox_table(op)
    for table in reversed(TENANT_TABLES):
        op.execute(f"DROP POLICY {table}_tenant_isolation ON {table}")
    op.drop_index("ix_review_task_open", table_name="review_task")
    op.drop_table("review_task")
    op.drop_table("profile_version")
    op.drop_table("profile_attribute")
    op.drop_index("ix_profile_node_parent", table_name="profile_node")
    op.drop_table("profile_node")
