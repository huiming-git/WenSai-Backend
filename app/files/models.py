from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlmodel import Field, Relationship, SQLModel


class TaskFile(SQLModel, table=True):
    __tablename__ = "task_files"

    id: int | None = Field(default=None, primary_key=True, index=True)
    user_id: int | None = Field(default=None, sa_column=Column(Integer, ForeignKey("users.id"), index=True, nullable=True))
    workspace_id: int | None = Field(default=None, sa_column=Column(Integer, ForeignKey("workspaces.id"), nullable=True))
    task_id: int = Field(sa_column=Column(Integer, ForeignKey("tasks.id"), index=True, nullable=False))
    filename: str = Field(sa_column=Column(String(255), nullable=False))
    mime_type: str | None = Field(default=None, sa_column=Column(String(120), nullable=True))
    storage_key: str = Field(sa_column=Column(String(500), nullable=False))
    size: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    source: str = Field(default="upload", sa_column=Column(String(40), nullable=False))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), nullable=False))

    task: "Task" = Relationship(back_populates="files")

    @property
    def content_type(self) -> str | None:
        return self.mime_type
