from datetime import datetime
from typing import Literal, Optional
from sqlmodel import Field, SQLModel

from app.users.schemas import UserResponse


class ReviewCreate(SQLModel):
    score: int = Field(ge=1, le=10)
    content: str
    recommendation: Literal["accept", "minor_revision", "major_revision", "reject"]


class ReviewUpdate(SQLModel):
    score: Optional[int] = Field(default=None, ge=1, le=10)
    content: Optional[str] = None
    recommendation: Optional[Literal["accept", "minor_revision", "major_revision", "reject"]] = None


class AIReviewCreateResponse(SQLModel):
    paper_id: int
    review_id: int
    task_id: str
    status: Literal["pending"]


class ReviewResponse(SQLModel):
    id: int
    paper_id: int
    reviewer_id: Optional[int] = None
    reviewer: Optional[UserResponse] = None
    source: Literal["manual", "ai"]
    status: Literal["pending", "running", "completed", "failed"] = "completed"
    score: Optional[int] = None
    content: Optional[str] = None
    recommendation: Optional[Literal["accept", "minor_revision", "major_revision", "reject"]] = None
    llm_log: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
