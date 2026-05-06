from datetime import datetime
from typing import Any

from sqlmodel import Field, SQLModel


class TaskCreate(SQLModel):
    title: str | None = Field(default=None, max_length=200)
    prompt: str = Field(min_length=1)
    agent_type: str = "hermes_acp"
    model: str = "default"
    input: dict[str, Any] | None = None
    runtime: str | None = None
    workspace_id: int | None = None
    dispatch: bool = True


class TaskResponse(SQLModel):
    model_config = {"from_attributes": True}

    id: int
    task_id: int | None = None
    user_id: int
    owner_id: int
    workspace_id: int | None = None
    workspace_root_path: str | None = None
    title: str | None = None
    agent_type: str
    model: str
    prompt: str
    runtime: str
    status: str
    input: dict[str, Any] | None = None
    result: dict[str, Any] | str | None = None
    error: str | None = None
    created_at: datetime
    queued_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime


class TaskCreateResponse(SQLModel):
    id: int
    task_id: int
    status: str


class TaskCancelResponse(SQLModel):
    task_id: int
    status: str


class TaskStartResponse(SQLModel):
    task_id: int
    status: str
