"""Create identity, patient, consent, goals, and audit tables.

Revision ID: 0001_identity_domain
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0001_identity_domain"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "professionals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("chat_id_digest", sa.String(length=64), unique=True, nullable=True),
        sa.Column("name_enc", sa.Text(), nullable=False),
        sa.Column("profession_enc", sa.Text(), nullable=False),
        sa.Column("council_registry_enc", sa.Text(), nullable=False),
        sa.Column("specialty_enc", sa.Text(), nullable=True),
        sa.Column(
            "timezone",
            sa.String(length=64),
            nullable=False,
            server_default="America/Fortaleza",
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "invitations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "professional_id",
            sa.String(length=36),
            sa.ForeignKey("professionals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_digest", sa.String(length=64), unique=True, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "patients",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "professional_id",
            sa.String(length=36),
            sa.ForeignKey("professionals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("display_name_enc", sa.Text(), nullable=False),
        sa.Column("alias_enc", sa.Text(), nullable=True),
        sa.Column("birth_date_enc", sa.Text(), nullable=True),
        sa.Column("template", sa.String(length=32), nullable=False, server_default="SOAP"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_patients_professional_status",
        "patients",
        ["professional_id", "active"],
    )
    op.create_table(
        "guardians",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "patient_id",
            sa.String(length=36),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name_enc", sa.Text(), nullable=False),
        sa.Column("relationship_enc", sa.Text(), nullable=False),
        sa.Column("contact_enc", sa.Text(), nullable=True),
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "patient_id",
            sa.String(length=36),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("terms_version", sa.String(length=64), nullable=False),
        sa.Column("purpose_enc", sa.Text(), nullable=False),
        sa.Column("evidence_ref_enc", sa.Text(), nullable=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_consents_patient_granted", "consents", ["patient_id", "granted_at"])
    op.create_table(
        "goals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "patient_id",
            sa.String(length=36),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("description_enc", sa.Text(), nullable=False),
        sa.Column("area_enc", sa.Text(), nullable=False),
        sa.Column("indicator_type", sa.String(length=32), nullable=False),
        sa.Column("mastery_criterion_enc", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_log_created_at", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_table("goals")
    op.drop_index("ix_consents_patient_granted", table_name="consents")
    op.drop_table("consents")
    op.drop_table("guardians")
    op.drop_index("ix_patients_professional_status", table_name="patients")
    op.drop_table("patients")
    op.drop_table("invitations")
    op.drop_table("professionals")
