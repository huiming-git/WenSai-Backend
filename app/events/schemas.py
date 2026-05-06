from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TaskEventCreate(BaseModel):
    type: str
    content: str | None = None
    metadata: dict[str, Any] | None = None
    message: str | None = None
    payload: dict[str, Any] | None = None


class TaskEventResponse(BaseModel):
    id: int
    task_id: int
    type: str
    content: str
    metadata: dict[str, Any]
    created_at: datetime
    seq: int | None = None
    message: str | None = None
    payload: dict[str, Any] | None = None


class TaskEventPage(BaseModel):
    items: list[TaskEventResponse]
    next_cursor: str | None = None
