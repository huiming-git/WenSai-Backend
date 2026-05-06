from datetime import datetime
from typing import Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlmodel import Field, Relationship, SQLModel


class Review(SQLModel, table=True):
    __tablename__ = "reviews"

    id: int | None = Field(default=None, primary_key=True, index=True)
    paper_id: int = Field(sa_column=Column(Integer, ForeignKey("papers.id"), nullable=False))
    reviewer_id: int | None = Field(default=None, sa_column=Column(Integer, ForeignKey("users.id"), nullable=True))
    source: str = Field(default="manual", sa_column=Column(String(10), nullable=False))
    status: str = Field(default="completed", sa_column=Column(String(20), nullable=False))
    score: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    content: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    recommendation: str | None = Field(default=None, sa_column=Column(String(20), nullable=True))
    llm_log: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), nullable=False))
    updated_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False))

    paper: "Paper" = Relationship(back_populates="reviews")
    reviewer: Optional["User"] = Relationship(back_populates="reviews")
