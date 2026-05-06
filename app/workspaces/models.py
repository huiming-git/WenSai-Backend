from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlmodel import Field, Relationship, SQLModel


class Workspace(SQLModel, table=True):
    __tablename__ = "workspaces"

    id: int | None = Field(default=None, primary_key=True, index=True)
    owner_id: int = Field(sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False))
    name: str = Field(sa_column=Column(String(120), nullable=False))
    invite_code: str = Field(sa_column=Column(String(32), unique=True, index=True, nullable=False))
    root_path: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), nullable=False))

    owner: "User" = Relationship(back_populates="workspaces", sa_relationship_kwargs={"foreign_keys": "Workspace.owner_id"})
    tasks: list["Task"] = Relationship(back_populates="workspace", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    memberships: list["WorkspaceMember"] = Relationship(
        back_populates="workspace",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class WorkspaceMember(SQLModel, table=True):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),)

    id: int | None = Field(default=None, primary_key=True, index=True)
    workspace_id: int = Field(sa_column=Column(Integer, ForeignKey("workspaces.id"), index=True, nullable=False))
    user_id: int = Field(sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False))
    role: str = Field(default="member", sa_column=Column(String(20), nullable=False, server_default="member"))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), nullable=False))

    workspace: "Workspace" = Relationship(back_populates="memberships")
    user: "User" = Relationship(back_populates="workspace_memberships")
