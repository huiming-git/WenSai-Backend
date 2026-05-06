from datetime import datetime
from typing import Optional
from sqlmodel import Field, SQLModel

from app.users.schemas import UserResponse


class PaperCreate(SQLModel):
    title: str
    abstract: Optional[str] = None


class PaperUpdate(SQLModel):
    title: Optional[str] = None
    abstract: Optional[str] = None
    status: Optional[str] = None


class PaperFinalize(SQLModel):
    decision: str  # accepted / rejected / revision
    score: int = Field(ge=1, le=10)
    comment: str


class PaperResponse(SQLModel):
    id: int
    title: str
    abstract: Optional[str]
    file_path: Optional[str]
    status: str
    author_id: int
    author: Optional[UserResponse] = None
    final_score: Optional[int] = None
    final_comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PaperListResponse(SQLModel):
    items: list[PaperResponse]
    total: int
    page: int
    page_size: int
