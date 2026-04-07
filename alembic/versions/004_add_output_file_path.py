"""add output_file_path to jobs

Revision ID: 004_output_path
Revises: 003_enrichment
Create Date: 2026-04-07 12:55:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_output_path"
down_revision: Union[str, None] = "003_enrichment"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("output_file_path", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "output_file_path")
