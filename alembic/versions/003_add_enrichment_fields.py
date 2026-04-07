"""add enrichment fields

Revision ID: 003_enrichment
Revises: d0e48f167723
Create Date: 2026-04-07 11:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003_enrichment"
down_revision: Union[str, None] = "d0e48f167723"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Job metrics columns
    op.add_column("jobs", sa.Column("processed_rows", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("cache_hits", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("api_calls", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("webhook_callbacks_received", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("jobs", sa.Column("webhook_timeouts", sa.Integer(), nullable=False, server_default="0"))

    # Contact apollo_id column with index
    op.add_column("contacts", sa.Column("apollo_id", sa.String(length=255), nullable=True))
    op.create_index(op.f("ix_contacts_apollo_id"), "contacts", ["apollo_id"], unique=False)

    # Partial unique index on linkedin_url (WHERE linkedin_url IS NOT NULL)
    op.execute(
        "CREATE UNIQUE INDEX ix_contacts_linkedin_url_unique ON contacts (linkedin_url) WHERE linkedin_url IS NOT NULL"
    )


def downgrade() -> None:
    # Remove partial unique index
    op.execute("DROP INDEX IF EXISTS ix_contacts_linkedin_url_unique")

    # Remove contact apollo_id
    op.drop_index(op.f("ix_contacts_apollo_id"), table_name="contacts")
    op.drop_column("contacts", "apollo_id")

    # Remove job metrics columns
    op.drop_column("jobs", "webhook_timeouts")
    op.drop_column("jobs", "webhook_callbacks_received")
    op.drop_column("jobs", "api_calls")
    op.drop_column("jobs", "cache_hits")
    op.drop_column("jobs", "processed_rows")
