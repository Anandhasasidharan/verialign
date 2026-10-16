"""initial

Revision ID: c791f6581406
Revises:
Create Date: 2026-06-07 11:30:48.628020

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c791f6581406"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "traces",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
        sa.Column("verification_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_traces_created_at", "traces", ["created_at"], unique=False)
    op.create_index("ix_traces_model", "traces", ["model"], unique=False)

    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.String(length=100), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("sentence_offset", sa.Integer(), nullable=True),
        sa.Column("sources_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["trace_id"], ["traces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claims_trace_id", "claims", ["trace_id"], unique=False)
    op.create_index("ix_claims_status", "claims", ["status"], unique=False)

    op.create_table(
        "contradictions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.Integer(), nullable=False),
        sa.Column("claim_a", sa.Text(), nullable=False),
        sa.Column("claim_b", sa.Text(), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(["trace_id"], ["traces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contradictions_trace_id", "contradictions", ["trace_id"], unique=False)

    op.create_table(
        "checklist_items",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("trace_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("priority", sa.String(length=20), nullable=False),
        sa.Column("related_claims_json", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["trace_id"], ["traces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_checklist_trace_id", "checklist_items", ["trace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_checklist_trace_id", table_name="checklist_items")
    op.drop_table("checklist_items")
    op.drop_index("ix_contradictions_trace_id", table_name="contradictions")
    op.drop_table("contradictions")
    op.drop_index("ix_claims_status", table_name="claims")
    op.drop_index("ix_claims_trace_id", table_name="claims")
    op.drop_table("claims")
    op.drop_index("ix_traces_model", table_name="traces")
    op.drop_index("ix_traces_created_at", table_name="traces")
    op.drop_table("traces")
