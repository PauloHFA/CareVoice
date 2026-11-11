"""Add encrypted asynchronous processing jobs.

Revision ID: 0002_processing_jobs
Revises: 0001_identity_domain
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002_processing_jobs"
down_revision: str | None = "0001_identity_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "processing_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "professional_id",
            sa.String(length=36),
            sa.ForeignKey("professionals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "patient_id",
            sa.String(length=36),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("payload_enc", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_processing_jobs_ready",
        "processing_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_processing_jobs_owner",
        "processing_jobs",
        ["professional_id", "patient_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_processing_jobs_owner", table_name="processing_jobs")
    op.drop_index("ix_processing_jobs_ready", table_name="processing_jobs")
    op.drop_table("processing_jobs")
