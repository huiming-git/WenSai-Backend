import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from redis.asyncio import Redis

from app.config import REDIS_URL
from app.database import SessionLocal
from app.tasks.models import Task
from app.users.models import User
from app.utils import decode_access_token

router = APIRouter(prefix="/ws/tasks", tags=["task-events-ws"])


@router.websocket("/{task_id}/events")
async def task_events_ws(websocket: WebSocket, task_id: int):
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    payload = decode_access_token(token)
    if payload is None or payload.get("sub") is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == int(payload["sub"])).first()
        task = db.query(Task).filter(Task.id == task_id, Task.owner_id == int(payload["sub"])).first()
        if not user or not task:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
    finally:
        db.close()

    await websocket.accept()
    redis = Redis.from_url(REDIS_URL, decode_responses=True)
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"task:{task_id}:events")
    try:
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            if message and message.get("data"):
                data = message["data"]
                await websocket.send_json(json.loads(data) if isinstance(data, str) else data)
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=0.01)
            except asyncio.TimeoutError:
                pass
    except WebSocketDisconnect:
        return
    finally:
        await pubsub.unsubscribe(f"task:{task_id}:events")
        await pubsub.close()
        await redis.close()
