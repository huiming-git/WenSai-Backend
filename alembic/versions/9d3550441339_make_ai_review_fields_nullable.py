"""make ai review fields nullable

Revision ID: 9d3550441339
Revises: e653cce7d20d
Create Date: 2026-04-25 13:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9d3550441339"
down_revision: Union[str, Sequence[str], None] = "e653cce7d20d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("reviews", "score", existing_type=sa.Integer(), nullable=True)
    op.alter_column("reviews", "content", existing_type=sa.Text(), nullable=True)
    op.alter_column("reviews", "recommendation", existing_type=sa.String(length=20), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE reviews SET score = 0 WHERE score IS NULL")
    op.execute("UPDATE reviews SET content = '' WHERE content IS NULL")
    op.execute("UPDATE reviews SET recommendation = 'minor_revision' WHERE recommendation IS NULL")
    op.alter_column("reviews", "recommendation", existing_type=sa.String(length=20), nullable=False)
    op.alter_column("reviews", "content", existing_type=sa.Text(), nullable=False)
    op.alter_column("reviews", "score", existing_type=sa.Integer(), nullable=False)
