from datetime import datetime

from sqlmodel import Field, SQLModel


class WorkspaceCreate(SQLModel):
    name: str = Field(min_length=1, max_length=120)


class WorkspaceJoin(SQLModel):
    invite_code: str = Field(min_length=1, max_length=32)


class WorkspaceResponse(SQLModel):
    model_config = {"from_attributes": True}

    id: int
    owner_id: int
    name: str
    invite_code: str
    role: str = "member"
    member_count: int = 0
    is_active: bool = False
    root_path: str | None = None
    created_at: datetime


class WorkspaceSwitchResponse(SQLModel):
    workspace_id: int
    active_workspace_id: int


class WorkspaceMemberResponse(SQLModel):
    id: int
    user_id: int
    username: str
    role: str
    created_at: datetime


class WorkspaceTaskSummary(SQLModel):
    id: int
    owner_id: int
    owner_username: str
    workspace_id: int | None = None
    title: str | None = None
    prompt: str
    status: str
    agent_type: str
    input: dict | None = None
    created_at: datetime
