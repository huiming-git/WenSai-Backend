from datetime import datetime
from typing import List, Optional

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, func
from sqlmodel import Field, Relationship, SQLModel


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True, index=True)
    username: str = Field(sa_column=Column(String(50), unique=True, index=True, nullable=False))
    hashed_password: str = Field(sa_column=Column(String(128), nullable=False))
    credits: int = Field(default=0, sa_column=Column(Integer, nullable=False, server_default="0"))
    active_workspace_id: int | None = Field(
        default=None,
        sa_column=Column(
            Integer,
            ForeignKey("workspaces.id", name="fk_users_active_workspace_id_workspaces", use_alter=True),
            index=True,
            nullable=True,
        ),
    )
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), nullable=False))

    papers: List["Paper"] = Relationship(back_populates="author", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    reviews: List["Review"] = Relationship(back_populates="reviewer", sa_relationship_kwargs={"cascade": "all, delete-orphan"})
    workspaces: List["Workspace"] = Relationship(
        back_populates="owner",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "foreign_keys": "Workspace.owner_id"},
    )
    active_workspace: Optional["Workspace"] = Relationship(sa_relationship_kwargs={"foreign_keys": "User.active_workspace_id"})
    workspace_memberships: List["WorkspaceMember"] = Relationship(
        back_populates="user",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    tasks: List["Task"] = Relationship(back_populates="owner", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


class CreditRedeemCode(SQLModel, table=True):
    __tablename__ = "credit_redeem_codes"

    id: int | None = Field(default=None, primary_key=True, index=True)
    code: str = Field(sa_column=Column(String(80), unique=True, index=True, nullable=False))
    credits: int = Field(sa_column=Column(Integer, nullable=False))
    status: str = Field(default="active", sa_column=Column(String(20), nullable=False, server_default="active"))
    used_by: int | None = Field(default=None, foreign_key="users.id", index=True)
    used_at: datetime | None = Field(default=None, sa_column=Column(DateTime, nullable=True))
    created_at: datetime | None = Field(default=None, sa_column=Column(DateTime, server_default=func.now(), nullable=False))
