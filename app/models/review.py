from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    paper_id: Mapped[int] = mapped_column(Integer, ForeignKey("papers.id"))
    reviewer_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)  # None for AI reviews
    source: Mapped[str] = mapped_column(String(10), default="manual")  # "ai" or "manual"
    status: Mapped[str] = mapped_column(String(20), default="completed")  # "pending" | "completed" | "failed"
    score: Mapped[int] = mapped_column(Integer)  # 1-10
    content: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(String(20))  # accept / minor_revision / major_revision / reject
    llm_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON log for AI call path/debug
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    paper = relationship("Paper", back_populates="reviews")
    reviewer = relationship("User", back_populates="reviews")
