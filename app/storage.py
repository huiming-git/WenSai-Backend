"""File storage abstraction – local filesystem or S3-compatible."""

import os
import shutil
import uuid
from abc import ABC, abstractmethod

from app.config import (
    STORAGE_BACKEND, UPLOAD_DIR,
    S3_BUCKET, S3_ENDPOINT_URL, S3_ACCESS_KEY, S3_SECRET_KEY, S3_REGION,
)


class StorageBackend(ABC):
    @abstractmethod
    def save(self, data: bytes, filename: str) -> str:
        """Save file and return the storage key."""

    @abstractmethod
    def save_file(self, file_path: str, filename: str) -> str:
        """Save a local file and return the storage key."""

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Read file bytes by key."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete file by key."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """Check if a file exists."""

    def local_path(self, key: str) -> str | None:
        """Return a local filesystem path if available (for LLM file upload)."""
        return None


class LocalStorage(StorageBackend):
    def __init__(self, base_dir: str = UPLOAD_DIR):
        self._dir = base_dir
        os.makedirs(self._dir, exist_ok=True)

    def _full_path(self, key: str) -> str:
        return os.path.join(self._dir, key)

    def save(self, data: bytes, filename: str) -> str:
        key = self._make_key(filename)
        with open(self._full_path(key), "wb") as f:
            f.write(data)
        return key

    def save_file(self, file_path: str, filename: str) -> str:
        key = self._make_key(filename)
        shutil.move(file_path, self._full_path(key))
        return key

    def _make_key(self, filename: str) -> str:
        ext = os.path.splitext(filename)[1] or ""
        return f"{uuid.uuid4().hex}{ext}"

    def read(self, key: str) -> bytes:
        with open(self._full_path(key), "rb") as f:
            return f.read()

    def delete(self, key: str) -> None:
        path = self._full_path(key)
        if os.path.exists(path):
            os.remove(path)

    def exists(self, key: str) -> bool:
        return os.path.exists(self._full_path(key))

    def local_path(self, key: str) -> str | None:
        p = self._full_path(key)
        return p if os.path.exists(p) else None


class S3Storage(StorageBackend):
    def __init__(self):
        import boto3
        kwargs = {
            "aws_access_key_id": S3_ACCESS_KEY,
            "aws_secret_access_key": S3_SECRET_KEY,
            "region_name": S3_REGION,
        }
        if S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = S3_ENDPOINT_URL
        self._client = boto3.client("s3", **kwargs)
        self._bucket = S3_BUCKET

    def save(self, data: bytes, filename: str) -> str:
        key = self._make_key(filename)
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)
        return key

    def save_file(self, file_path: str, filename: str) -> str:
        key = self._make_key(filename)
        with open(file_path, "rb") as file_obj:
            self._client.upload_fileobj(file_obj, self._bucket, key)
        return key

    def _make_key(self, filename: str) -> str:
        ext = os.path.splitext(filename)[1] or ""
        return f"uploads/{uuid.uuid4().hex}{ext}"

    def read(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=key)
        return resp["Body"].read()

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=key)
            return True
        except Exception:
            return False

    def local_path(self, key: str) -> str | None:
        # S3 has no local path; callers should use read() + temp file if needed
        return None


def get_storage() -> StorageBackend:
    if STORAGE_BACKEND == "s3":
        return S3Storage()
    return LocalStorage()


# Singleton instance used across the app
storage = get_storage()
