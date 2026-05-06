import json
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.events.service import EventService
from app.tasks.models import Task
from app.tasks.schemas import TaskResponse

VALID_TASK_STATUSES = {"pending", "queued", "running", "waiting_approval", "completed", "failed", "cancelling", "cancelled"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def encode_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)


def decode_json(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def task_to_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        task_id=task.id,
        user_id=task.owner_id,
        owner_id=task.owner_id,
        workspace_id=task.workspace_id,
        workspace_root_path=task.workspace.root_path if task.workspace else None,
        title=task.title,
        agent_type=task.agent_type,
        model=task.model,
        prompt=task.prompt,
        runtime=task.runtime,
        status=task.status,
        input=decode_json(task.input),
        result=decode_json(task.result),
        error=task.error,
        created_at=task.created_at,
        queued_at=task.queued_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        updated_at=task.updated_at,
    )


async def set_task_status(db: Session, task: Task, status: str, content: str | None = None) -> TaskResponse:
    if status not in VALID_TASK_STATUSES:
        raise ValueError(f"Invalid task status: {status}")

    now = datetime.utcnow()
    task.status = status
    if status == "queued" and task.queued_at is None:
        task.queued_at = now
    if status == "running" and task.started_at is None:
        task.started_at = now
    if status in TERMINAL_STATUSES and task.completed_at is None:
        task.completed_at = now
    db.commit()
    db.refresh(task)
    await EventService(db).create_event(
        task.id,
        "task_status_changed",
        content or f"任务状态变更为 {status}",
        {"status": status},
    )
    if status == "queued":
        await EventService(db).create_event(task.id, "task_queued", "任务已进入队列", {"status": status})
    elif status == "running":
        await EventService(db).create_event(task.id, "task_started", "任务开始执行", {"status": status})
    elif status == "completed":
        await EventService(db).create_event(task.id, "task_completed", "任务完成", {"status": status})
    elif status == "failed":
        await EventService(db).create_event(task.id, "task_failed", task.error or "任务失败", {"status": status})
    elif status == "cancelled":
        await EventService(db).create_event(task.id, "task_cancelled", "任务已取消", {"status": status})
    return task_to_response(task)
