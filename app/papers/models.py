from datetime import datetime
from typing import List

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlmodel import Field, Relationship, SQLModel


class Paper(SQLModel, table=True):
    __tablename__ = "papers"

    id: int | None = Field(default=None, primary_key=True, index=True)
    title: str = Field(sa_column=Column(String(200), nullable=False))
    abstract: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    file_path: str | None = Field(default=None, sa_column=Column(String(500), nullable=True))
    status: str = Field(default="pending", sa_column=Column(String(20), nullable=False))
    author_id: int = Field(sa_column=Column(Integer, ForeignKey("users.id"), nullable=False))
    final_score: int | None = Field(default=None, sa_column=Column(Integer, nullable=True))
    final_comment: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), nullable=False))
    updated_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False))

    author: "User" = Relationship(back_populates="papers")
    reviews: List["Review"] = Relationship(back_populates="paper", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
