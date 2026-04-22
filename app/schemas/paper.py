from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.user import UserResponse


class PaperCreate(BaseModel):
    title: str
    abstract: Optional[str] = None


class PaperUpdate(BaseModel):
    title: Optional[str] = None
    abstract: Optional[str] = None
    status: Optional[str] = None


class PaperFinalize(BaseModel):
    decision: str  # accepted / rejected / revision
    score: int = Field(ge=1, le=10)
    comment: str


class PaperResponse(BaseModel):
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


class PaperListResponse(BaseModel):
    items: list[PaperResponse]
    total: int
    page: int
    page_size: int
