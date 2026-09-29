"""add suggested_attributes to enrichment_versions

Revision ID: a3f1c9d2b7e4
Revises: edc485ec639c
Create Date: 2026-09-29 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f1c9d2b7e4"
down_revision: Union[str, None] = "edc485ec639c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "enrichment_versions",
        sa.Column("suggested_attributes", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("enrichment_versions", "suggested_attributes")
