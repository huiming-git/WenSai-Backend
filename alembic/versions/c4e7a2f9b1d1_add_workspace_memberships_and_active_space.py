"""add workspace memberships and active space

Revision ID: c4e7a2f9b1d1
Revises: 8b1f2a4c9d0e
Create Date: 2026-04-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4e7a2f9b1d1"
down_revision: Union[str, Sequence[str], None] = "8b1f2a4c9d0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("active_workspace_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_users_active_workspace_id"), "users", ["active_workspace_id"], unique=False)
    op.create_foreign_key("fk_users_active_workspace_id_workspaces", "users", "workspaces", ["active_workspace_id"], ["id"])

    op.add_column("workspaces", sa.Column("invite_code", sa.String(length=32), nullable=True))
    op.create_index(op.f("ix_workspaces_invite_code"), "workspaces", ["invite_code"], unique=True)

    op.create_table(
        "workspace_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
    )
    op.create_index(op.f("ix_workspace_members_id"), "workspace_members", ["id"], unique=False)
    op.create_index(op.f("ix_workspace_members_workspace_id"), "workspace_members", ["workspace_id"], unique=False)
    op.create_index(op.f("ix_workspace_members_user_id"), "workspace_members", ["user_id"], unique=False)

    conn = op.get_bind()
    workspaces = conn.execute(sa.text("SELECT id, owner_id FROM workspaces ORDER BY id ASC")).mappings().all()
    for workspace in workspaces:
        invite_code = f"WS{workspace['id']:04d}{workspace['owner_id']:04d}"
        conn.execute(
            sa.text("UPDATE workspaces SET invite_code = :invite_code WHERE id = :workspace_id"),
            {"invite_code": invite_code, "workspace_id": workspace["id"]},
        )
        conn.execute(
            sa.text(
                "INSERT INTO workspace_members (workspace_id, user_id, role) "
                "VALUES (:workspace_id, :user_id, 'owner') "
                "ON CONFLICT (workspace_id, user_id) DO NOTHING"
            ),
            {"workspace_id": workspace["id"], "user_id": workspace["owner_id"]},
        )

    first_memberships = conn.execute(
        sa.text("SELECT user_id, MIN(workspace_id) AS workspace_id FROM workspace_members GROUP BY user_id")
    ).mappings().all()
    for membership in first_memberships:
        conn.execute(
            sa.text("UPDATE users SET active_workspace_id = :workspace_id WHERE id = :user_id"),
            {"workspace_id": membership["workspace_id"], "user_id": membership["user_id"]},
        )

    op.alter_column("workspaces", "invite_code", existing_type=sa.String(length=32), nullable=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_workspace_members_user_id"), table_name="workspace_members")
    op.drop_index(op.f("ix_workspace_members_workspace_id"), table_name="workspace_members")
    op.drop_index(op.f("ix_workspace_members_id"), table_name="workspace_members")
    op.drop_table("workspace_members")

    op.drop_index(op.f("ix_workspaces_invite_code"), table_name="workspaces")
    op.drop_column("workspaces", "invite_code")

    op.drop_constraint("fk_users_active_workspace_id_workspaces", "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_active_workspace_id"), table_name="users")
    op.drop_column("users", "active_workspace_id")
