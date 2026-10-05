"""Store deduplicated external source snapshots."""

from alembic import op
import sqlalchemy as sa

revision = "002_external_snapshots"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("data_type", sa.String(length=64), nullable=False),
        sa.Column("source_url", sa.String(length=1000), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id",
            "source",
            "data_type",
            "content_hash",
            name="uq_external_snapshot_content",
        ),
    )
    op.create_index(
        op.f("ix_external_snapshots_company_id"),
        "external_snapshots",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_external_snapshots_content_hash"),
        "external_snapshots",
        ["content_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_external_snapshots_content_hash"), table_name="external_snapshots")
    op.drop_index(op.f("ix_external_snapshots_company_id"), table_name="external_snapshots")
    op.drop_table("external_snapshots")
