from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlmodel import Field, Relationship, SQLModel


class TaskEvent(SQLModel, table=True):
    __tablename__ = "task_events"
    __table_args__ = (
        UniqueConstraint("task_id", "seq", name="uq_task_events_task_seq"),
        Index("ix_task_events_task_created", "task_id", "created_at"),
    )

    id: int | None = Field(default=None, primary_key=True, index=True)
    task_id: int = Field(sa_column=Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False))
    seq: int = Field(sa_column=Column(Integer, nullable=False))
    type: str = Field(sa_column=Column(String(60), index=True, nullable=False))
    level: str = Field(default="info", sa_column=Column(String(20), nullable=False))
    message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    payload: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    content: str = Field(default="", sa_column=Column(Text, nullable=False))
    metadata_json: str | None = Field(default=None, sa_column=Column("metadata", Text, nullable=True))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), index=True, nullable=False))

    task: "Task" = Relationship(back_populates="events")
