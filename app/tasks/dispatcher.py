import logging

import httpx
from sqlalchemy.orm import Session

from app.config import AGENTSDK_BASE_URL, INTERNAL_API_TOKEN
from app.tasks.models import Task

logger = logging.getLogger(__name__)


async def dispatch_task_to_agentsdk(task_id: int) -> None:
    """Ask agentsdk to run a task.

    Backend only sends the task id. agentsdk reads task details through
    backend internal APIs and writes all execution state/events back.
    """
    url = f"{AGENTSDK_BASE_URL.rstrip('/')}/internal/agent-runs"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                url,
                json={"task_id": task_id},
                headers={"X-Internal-Token": INTERNAL_API_TOKEN},
            )
            response.raise_for_status()
    except Exception:
        logger.exception("Failed to dispatch task %s to agentsdk", task_id)


async def redispatch_queued_tasks(db: Session) -> list[int]:
    """Re-dispatch queued tasks that never transitioned into running.

    This compensates for cases where Backend accepted the task while AgentSDK
    was offline, leaving the task stuck in queued state indefinitely.
    """
    queued_tasks = (
        db.query(Task)
        .filter(Task.status == "queued", Task.started_at.is_(None), Task.completed_at.is_(None))
        .order_by(Task.queued_at.asc().nullsfirst(), Task.id.asc())
        .all()
    )

    redispatched: list[int] = []
    for task in queued_tasks:
        await dispatch_task_to_agentsdk(task.id)
        redispatched.append(task.id)
    return redispatched


async def transfer_file_to_agentsdk(
    task_id: int,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    relative_path: str | None = None,
    workspace_root_path: str | None = None,
) -> dict | None:
    """Copy an uploaded task file into the AgentSDK task sandbox."""
    url = f"{AGENTSDK_BASE_URL.rstrip('/')}/internal/tasks/{task_id}/sandbox/files"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                url,
                headers={"X-Internal-Token": INTERNAL_API_TOKEN},
                files={"file": (filename, data, content_type or "application/octet-stream")},
                data={
                    "relative_path": relative_path or filename,
                    **({"workspace_root_path": workspace_root_path} if workspace_root_path else {}),
                },
            )
            response.raise_for_status()
            return response.json()
    except Exception:
        logger.exception("Failed to transfer task file to agentsdk sandbox: task_id=%s filename=%s", task_id, filename)
        return None


async def cleanup_task_sandbox_from_agentsdk(task_id: int, workspace_root_path: str | None = None) -> None:
    """Ask agentsdk to delete the task workspace after Backend deletes a sandbox."""
    url = f"{AGENTSDK_BASE_URL.rstrip('/')}/internal/tasks/{task_id}/sandbox"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(
                "DELETE",
                url,
                headers={"X-Internal-Token": INTERNAL_API_TOKEN},
                json={"workspace_root_path": workspace_root_path},
            )
            response.raise_for_status()
    except Exception:
        logger.exception("Failed to cleanup agentsdk sandbox: task_id=%s", task_id)


async def delete_file_from_agentsdk_sandbox(
    task_id: int,
    relative_path: str,
    area: str = "input",
    workspace_root_path: str | None = None,
) -> bool:
    """Delete a single file from the AgentSDK task sandbox input directory."""
    url = f"{AGENTSDK_BASE_URL.rstrip('/')}/internal/tasks/{task_id}/sandbox/files"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.request(
                "DELETE",
                url,
                headers={"X-Internal-Token": INTERNAL_API_TOKEN},
                json={
                    "relative_path": relative_path,
                    "area": area,
                    **({"workspace_root_path": workspace_root_path} if workspace_root_path else {}),
                },
            )
            response.raise_for_status()
            return True
    except Exception:
        logger.exception("Failed to delete agentsdk sandbox file: task_id=%s relative_path=%s", task_id, relative_path)
        return False
