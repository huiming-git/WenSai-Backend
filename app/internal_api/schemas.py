from typing import Any

from pydantic import BaseModel


class TaskStatusUpdate(BaseModel):
    status: str


class TaskResultUpdate(BaseModel):
    result: dict[str, Any] | str | None = None
    message: str | None = None
    files: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    status: str = "completed"


class TaskErrorUpdate(BaseModel):
    error: str
    metadata: dict[str, Any] | None = None
    status: str = "failed"
