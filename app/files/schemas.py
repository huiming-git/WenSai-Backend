from datetime import datetime

from sqlmodel import SQLModel


class TaskFileCreate(SQLModel):
    filename: str
    kind: str = "file"
    content: str = ""


class TaskFileResponse(SQLModel):
    model_config = {"from_attributes": True}

    id: int
    user_id: int | None = None
    workspace_id: int | None = None
    task_id: int
    filename: str
    mime_type: str | None = None
    content_type: str | None = None
    size: int
    checksum: str | None = None
    source: str = "upload"
    storage_key: str | None = None
    created_at: datetime


class WorkspaceFileResponse(SQLModel):
    id: int
    user_id: int | None = None
    workspace_id: int | None = None
    task_id: int
    filename: str
    mime_type: str | None = None
    size: int
    checksum: str | None = None
    source: str = "upload"
    created_at: datetime


class FilePreviewResponse(SQLModel):
    id: int
    filename: str
    mime_type: str | None = None
    size: int
    mode: str
    content: str | None = None
    page_count: int = 0
    page_image_urls: list[str] = []
    download_url: str | None = None
    message: str | None = None
