from datetime import datetime
from typing import Any

from sqlmodel import SQLModel


class ApprovalCreate(SQLModel):
    action_type: str | None = None
    risk_level: str | None = None
    description: str | None = None
    payload: dict[str, Any] | None = None
    action: str | None = None
    risk: str | None = None


class ApprovalDecision(SQLModel):
    response: dict[str, Any] | None = None


class ApprovalResponse(SQLModel):
    model_config = {"from_attributes": True}

    id: int
    approval_id: int | None = None
    task_id: int
    status: str
    action_type: str
    risk_level: str
    description: str
    payload: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: int | None = None
    action: str | None = None
    risk: str | None = None
    decided_at: datetime | None = None
