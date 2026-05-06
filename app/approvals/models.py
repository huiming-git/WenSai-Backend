from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlmodel import Field, Relationship, SQLModel


class TaskApproval(SQLModel, table=True):
    __tablename__ = "task_approvals"

    id: int | None = Field(default=None, primary_key=True, index=True)
    task_id: int = Field(sa_column=Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False))
    status: str = Field(default="pending", sa_column=Column(String(20), index=True, nullable=False))
    action_type: str = Field(sa_column=Column(String(120), nullable=False))
    risk_level: str = Field(default="medium", sa_column=Column(String(20), nullable=False))
    description: str = Field(default="", sa_column=Column(Text, nullable=False))
    payload: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    response: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), nullable=False))
    resolved_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    resolved_by: int | None = Field(default=None, sa_column=Column(Integer, ForeignKey("users.id"), nullable=True))

    task: "Task" = Relationship(back_populates="approvals")

    @property
    def action(self) -> str:
        return self.description or self.action_type

    @property
    def risk(self) -> str:
        return self.risk_level

    @property
    def decided_at(self) -> datetime | None:
        return self.resolved_at
