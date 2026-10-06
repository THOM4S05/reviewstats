"""unique POS table sessions per business

Revision ID: a91e62d7f410
Revises: 8b31a4f2c9d0
Create Date: 2026-08-30
"""
from typing import Sequence, Union

from alembic import op


revision: str = "a91e62d7f410"
down_revision: Union[str, None] = "8b31a4f2c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("table_sessions") as batch:
        batch.create_unique_constraint(
            "uq_table_sessions_business_external", ["business_id", "external_session_id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("table_sessions") as batch:
        batch.drop_constraint("uq_table_sessions_business_external", type_="unique")
