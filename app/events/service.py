import json
import logging
from typing import Any

from fastapi.encoders import jsonable_encoder
from redis import Redis
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.config import REDIS_URL
from app.events.models import TaskEvent
from app.events.schemas import TaskEventResponse
from app.realtime.manager import task_ws_manager

logger = logging.getLogger(__name__)

TASK_EVENT_TYPES = {
    "task_created",
    "task_queued",
    "task_started",
    "task_status_changed",
    "agent_runtime_started",
    "agent_runtime_stopped",
    "agent_thinking",
    "agent_message",
    "tool_call_started",
    "tool_call_finished",
    "tool_call_failed",
    "browser_action",
    "terminal_command",
    "file_diff",
    "file_created",
    "file_saved",
    "approval_required",
    "approval_approved",
    "approval_rejected",
    "approval_expired",
    "task_completed",
    "task_failed",
    "task_cancelled",
}


class EventService:
    def __init__(self, db: Session, redis_url: str = REDIS_URL) -> None:
        self.db = db
        self.redis_url = redis_url

    async def create_event(
        self,
        task_id: int,
        event_type: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
        commit: bool = True,
    ) -> TaskEventResponse:
        # Agent runtimes can stream multiple event chunks concurrently. Lock per
        # task before assigning seq so (task_id, seq) remains gapless and unique.
        self.db.execute(text("SELECT pg_advisory_xact_lock(:task_id)"), {"task_id": task_id})
        max_seq = self.db.query(func.max(TaskEvent.seq)).filter(TaskEvent.task_id == task_id).scalar() or 0
        event = TaskEvent(
            task_id=task_id,
            seq=max_seq + 1,
            type=event_type,
            level="info",
            message=content or "",
            payload=json.dumps(metadata or {}, ensure_ascii=False),
            content=content or "",
            metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
        )
        self.db.add(event)
        if commit:
            self.db.commit()
            self.db.refresh(event)
        dto = event_to_response(event)
        payload = {"event": "task_event", "data": jsonable_encoder(dto)}
        await self.publish(task_id, payload)
        return dto

    async def publish(self, task_id: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, default=str)
        try:
            Redis.from_url(self.redis_url, decode_responses=True).publish(f"task:{task_id}:events", encoded)
        except Exception:
            logger.exception("Failed to publish task event to Redis: task_id=%s", task_id)
        await task_ws_manager.broadcast(task_id, payload)


def _decode_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"value": value}
    except json.JSONDecodeError:
        return {"raw": raw}


def event_to_response(event: TaskEvent) -> TaskEventResponse:
    metadata = _decode_metadata(event.metadata_json)
    return TaskEventResponse(
        id=event.id,
        task_id=event.task_id,
        seq=event.seq,
        type=event.type,
        content=event.content,
        metadata=metadata,
        message=event.content,
        payload=metadata,
        created_at=event.created_at,
    )


async def create_task_event(
    db: Session,
    task_id: int,
    event_type: str,
    level: str = "info",
    message: str | None = None,
    payload: dict[str, Any] | None = None,
    commit: bool = True,
) -> TaskEvent:
    dto = await EventService(db).create_event(task_id, event_type, message, payload, commit)
    return db.query(TaskEvent).filter(TaskEvent.id == dto.id).first()
