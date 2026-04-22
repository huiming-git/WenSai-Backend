from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.schemas.user import UserResponse


class ReviewCreate(BaseModel):
    score: int = Field(ge=1, le=10)
    content: str
    recommendation: str  # accept / minor_revision / major_revision / reject


class ReviewUpdate(BaseModel):
    score: Optional[int] = Field(default=None, ge=1, le=10)
    content: Optional[str] = None
    recommendation: Optional[str] = None


class ReviewResponse(BaseModel):
    id: int
    paper_id: int
    reviewer_id: Optional[int] = None
    reviewer: Optional[UserResponse] = None
    source: str  # "ai" or "manual"
    status: str = "completed"  # "pending" | "completed" | "failed"
    score: int
    content: str
    recommendation: str
    llm_log: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
