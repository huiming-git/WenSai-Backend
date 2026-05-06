from datetime import datetime

from sqlmodel import SQLModel


class ActiveWorkspaceSummary(SQLModel):
    id: int
    name: str
    invite_code: str

    model_config = {"from_attributes": True}


class UserResponse(SQLModel):
    id: int
    username: str
    credits: int
    active_workspace_id: int | None = None
    active_workspace: ActiveWorkspaceSummary | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CreditBalanceResponse(SQLModel):
    credits: int


class RedeemCodeRequest(SQLModel):
    code: str


class RedeemCodeResponse(SQLModel):
    credits: int
    added: int
    code: str
    message: str
