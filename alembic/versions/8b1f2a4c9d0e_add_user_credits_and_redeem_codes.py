"""add user credits and redeem codes

Revision ID: 8b1f2a4c9d0e
Revises: 6a8c1d7e5b2f
Create Date: 2026-04-25 23:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "8b1f2a4c9d0e"
down_revision: Union[str, Sequence[str], None] = "6a8c1d7e5b2f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("credits", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "credit_redeem_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("used_by", sa.Integer(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_credit_redeem_codes_code", "credit_redeem_codes", ["code"], unique=True)
    op.create_index("ix_credit_redeem_codes_used_by", "credit_redeem_codes", ["used_by"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_credit_redeem_codes_used_by", table_name="credit_redeem_codes")
    op.drop_index("ix_credit_redeem_codes_code", table_name="credit_redeem_codes")
    op.drop_table("credit_redeem_codes")
    op.drop_column("users", "credits")
