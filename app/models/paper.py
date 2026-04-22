from datetime import datetime
from typing import Optional

from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    abstract: Mapped[str] = mapped_column(Text, nullable=True)  # 评审要求/instructions for AI
    file_path: Mapped[str] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"))
    final_score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    final_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    author = relationship("User", back_populates="papers")
    reviews = relationship("Review", back_populates="paper", cascade="all, delete-orphan")
