"""agent realtime events

Revision ID: 6a8c1d7e5b2f
Revises: 2f4d9b1a8c73
Create Date: 2026-04-25 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "6a8c1d7e5b2f"
down_revision: Union[str, Sequence[str], None] = "2f4d9b1a8c73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("agent_type", sa.String(length=50), nullable=False, server_default="hermes_acp"))
    op.add_column("tasks", sa.Column("model", sa.String(length=100), nullable=False, server_default="default"))
    op.add_column("tasks", sa.Column("input", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("queued_at", sa.DateTime(), nullable=True))
    op.add_column("tasks", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("tasks", sa.Column("completed_at", sa.DateTime(), nullable=True))

    op.add_column("task_events", sa.Column("content", sa.Text(), nullable=False, server_default=""))
    op.add_column("task_events", sa.Column("metadata", sa.Text(), nullable=True))
    op.execute("UPDATE task_events SET content = COALESCE(message, ''), metadata = payload")
    op.create_index("ix_task_events_task_created", "task_events", ["task_id", "created_at"], unique=False)

    op.add_column("task_approvals", sa.Column("action_type", sa.String(length=120), nullable=False, server_default="agent.permission"))
    op.add_column("task_approvals", sa.Column("risk_level", sa.String(length=20), nullable=False, server_default="medium"))
    op.add_column("task_approvals", sa.Column("description", sa.Text(), nullable=False, server_default=""))
    op.add_column("task_approvals", sa.Column("resolved_at", sa.DateTime(), nullable=True))
    op.add_column("task_approvals", sa.Column("resolved_by", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_task_approvals_resolved_by_users", "task_approvals", "users", ["resolved_by"], ["id"])
    op.execute(
        "UPDATE task_approvals SET action_type = COALESCE(action, 'agent.permission'), "
        "risk_level = COALESCE(risk, 'medium'), description = COALESCE(action, ''), resolved_at = decided_at"
    )

    op.add_column("task_files", sa.Column("user_id", sa.Integer(), nullable=True))
    op.add_column("task_files", sa.Column("workspace_id", sa.Integer(), nullable=True))
    op.add_column("task_files", sa.Column("mime_type", sa.String(length=120), nullable=True))
    op.add_column("task_files", sa.Column("source", sa.String(length=40), nullable=False, server_default="upload"))
    op.create_foreign_key("fk_task_files_user_id_users", "task_files", "users", ["user_id"], ["id"])
    op.create_foreign_key("fk_task_files_workspace_id_workspaces", "task_files", "workspaces", ["workspace_id"], ["id"])
    op.execute(
        "UPDATE task_files f SET user_id = t.owner_id, workspace_id = t.workspace_id, mime_type = f.content_type "
        "FROM tasks t WHERE f.task_id = t.id"
    )
    op.create_index("ix_task_files_user_id", "task_files", ["user_id"], unique=False)
    op.create_index("ix_task_files_workspace_id", "task_files", ["workspace_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_task_files_workspace_id", table_name="task_files")
    op.drop_index("ix_task_files_user_id", table_name="task_files")
    op.drop_constraint("fk_task_files_workspace_id_workspaces", "task_files", type_="foreignkey")
    op.drop_constraint("fk_task_files_user_id_users", "task_files", type_="foreignkey")
    op.drop_column("task_files", "source")
    op.drop_column("task_files", "mime_type")
    op.drop_column("task_files", "workspace_id")
    op.drop_column("task_files", "user_id")

    op.drop_constraint("fk_task_approvals_resolved_by_users", "task_approvals", type_="foreignkey")
    op.drop_column("task_approvals", "resolved_by")
    op.drop_column("task_approvals", "resolved_at")
    op.drop_column("task_approvals", "description")
    op.drop_column("task_approvals", "risk_level")
    op.drop_column("task_approvals", "action_type")

    op.drop_index("ix_task_events_task_created", table_name="task_events")
    op.drop_column("task_events", "metadata")
    op.drop_column("task_events", "content")

    op.drop_column("tasks", "completed_at")
    op.drop_column("tasks", "started_at")
    op.drop_column("tasks", "queued_at")
    op.drop_column("tasks", "input")
    op.drop_column("tasks", "model")
    op.drop_column("tasks", "agent_type")
