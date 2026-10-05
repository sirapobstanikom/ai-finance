"""Initial schema. Upgrade creates the current models. Downgrade drops them."""

from alembic import op

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from aivi.domain.models import Base

    tables = [
        table for name, table in Base.metadata.tables.items() if name != "external_snapshots"
    ]
    Base.metadata.create_all(op.get_bind(), tables=tables)


def downgrade() -> None:
    from aivi.domain.models import Base

    Base.metadata.drop_all(op.get_bind())
