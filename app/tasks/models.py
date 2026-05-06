from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlmodel import Field, Relationship, SQLModel


class Task(SQLModel, table=True):
    __tablename__ = "tasks"

    id: int | None = Field(default=None, primary_key=True, index=True)
    owner_id: int = Field(sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=False))
    workspace_id: int | None = Field(default=None, sa_column=Column(Integer, ForeignKey("workspaces.id"), nullable=True))
    title: str = Field(sa_column=Column(String(200), nullable=False))
    prompt: str = Field(sa_column=Column(Text, nullable=False))
    runtime: str = Field(default="hermes-acp", sa_column=Column(String(50), nullable=False))
    agent_type: str = Field(default="hermes_acp", sa_column=Column(String(50), nullable=False))
    model: str = Field(default="default", sa_column=Column(String(100), nullable=False))
    input: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    status: str = Field(default="pending", sa_column=Column(String(30), index=True, nullable=False))
    result: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    queued_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    started_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    completed_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), nullable=False))
    updated_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False))

    owner: "User" = Relationship(back_populates="tasks")
    workspace: Optional["Workspace"] = Relationship(back_populates="tasks")
    events: List["TaskEvent"] = Relationship(back_populates="task", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    approvals: List["TaskApproval"] = Relationship(back_populates="task", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    files: List["TaskFile"] = Relationship(back_populates="task", sa_relationship_kwargs={"cascade": "all, delete-orphan"})

    @property
    def user_id(self) -> int:
        return self.owner_id
