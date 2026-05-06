import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

import json
from datetime import datetime

from app.approvals.models import TaskApproval
from app.approvals.schemas import ApprovalDecision, ApprovalResponse
from app.config import DISPATCH_AGENT_TASKS, PREVIEW_CACHE_DIR
from app.dependencies import get_current_user, get_db
from app.events.models import TaskEvent
from app.events.schemas import TaskEventPage, TaskEventResponse
from app.events.service import EventService, event_to_response
from app.files.models import TaskFile
from app.storage import storage
from app.tasks.dispatcher import cleanup_task_sandbox_from_agentsdk, dispatch_task_to_agentsdk, transfer_file_to_agentsdk
from app.tasks.models import Task
from app.tasks.schemas import TaskCancelResponse, TaskCreate, TaskCreateResponse, TaskResponse, TaskStartResponse
from app.tasks.service import encode_json, set_task_status, task_to_response
from app.users.models import User
from app.workspaces.models import WorkspaceMember
from app.workspaces.service import ensure_active_workspace, get_workspace_for_member

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
logger = logging.getLogger(__name__)


def _get_accessible_task(db: Session, task_id: int, user_id: int) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    if task.owner_id == user_id:
        return task
    if task.workspace_id is not None:
        membership = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.workspace_id == task.workspace_id, WorkspaceMember.user_id == user_id)
            .first()
        )
        if membership:
            return task
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


def _cleanup_task_files(db: Session, task_files: list[TaskFile]) -> None:
    deleting_ids = [task_file.id for task_file in task_files if task_file.id is not None]
    storage_keys = {task_file.storage_key for task_file in task_files}

    for task_file in task_files:
        preview_dir = Path(PREVIEW_CACHE_DIR) / f"file-{task_file.id}"
        if preview_dir.exists():
            shutil.rmtree(preview_dir)

    for storage_key in storage_keys:
        remaining_refs = (
            db.query(TaskFile.id)
            .filter(TaskFile.storage_key == storage_key, TaskFile.id.notin_(deleting_ids))
            .first()
        )
        if remaining_refs:
            continue

        try:
            storage.delete(storage_key)
        except Exception:
            logger.exception("Failed to delete task file storage: storage_key=%s", storage_key)


def _decode(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


def _build_parent_context(db: Session, parent_task_id: int, user_id: int) -> str | None:
    parent = _get_accessible_task(db, parent_task_id, user_id)
    parent_result = _decode(parent.result)
    parent_message = ""
    if isinstance(parent_result, dict):
        parent_message = str(parent_result.get("message") or "")
    elif parent_result is not None:
        parent_message = str(parent_result)

    parts = [
        f"# 上一轮沙盒对话 #{parent.id}",
        "",
        f"标题：{parent.title or ''}",
        f"状态：{parent.status}",
        "",
        "## 上一轮用户输入",
        parent.prompt or "",
    ]
    if parent_message:
        parts.extend(["", "## 上一轮 Agent 输出", parent_message])
    if parent.error:
        parts.extend(["", "## 上一轮错误", parent.error])
    return "\n".join(parts).strip()


def _enrich_follow_up_input(db: Session, task_input: dict, user_id: int) -> dict:
    parent_task_id = task_input.get("parent_task_id")
    if parent_task_id is None:
        return task_input
    try:
        normalized_parent_id = int(parent_task_id)
    except (TypeError, ValueError):
        return task_input
    enriched = dict(task_input)
    if not enriched.get("conversation_context"):
        enriched["conversation_context"] = _build_parent_context(db, normalized_parent_id, user_id)

    parent = _get_accessible_task(db, normalized_parent_id, user_id)
    parent_file_ids = [
        file_id
        for (file_id,) in db.query(TaskFile.id).filter(TaskFile.task_id == parent.id).order_by(TaskFile.id.asc()).all()
        if file_id is not None
    ]
    existing_file_ids = enriched.get("workspace_file_ids")
    if not isinstance(existing_file_ids, list):
        existing_file_ids = []
    merged_file_ids = list(dict.fromkeys([*parent_file_ids, *existing_file_ids]))
    if merged_file_ids:
        enriched["workspace_file_ids"] = merged_file_ids
    return enriched


def _approval_response(approval: TaskApproval) -> ApprovalResponse:
    return ApprovalResponse(
        id=approval.id,
        approval_id=approval.id,
        task_id=approval.task_id,
        status=approval.status,
        action_type=approval.action_type,
        risk_level=approval.risk_level,
        description=approval.description,
        payload=_decode(approval.payload),
        response=_decode(approval.response),
        created_at=approval.created_at,
        resolved_at=approval.resolved_at,
        resolved_by=approval.resolved_by,
        action=approval.action,
        risk=approval.risk,
        decided_at=approval.decided_at,
    )


def _get_accessible_task_file(db: Session, file_id: int, user_id: int) -> TaskFile:
    task_file = (
        db.query(TaskFile)
        .join(Task, Task.id == TaskFile.task_id)
        .outerjoin(
            WorkspaceMember,
            (WorkspaceMember.workspace_id == Task.workspace_id) & (WorkspaceMember.user_id == user_id),
        )
        .filter(TaskFile.id == file_id)
        .filter((Task.owner_id == user_id) | (WorkspaceMember.id.isnot(None)))
        .first()
    )
    if not task_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Workspace file {file_id} not found")
    return task_file


async def _attach_workspace_files_to_task(db: Session, task: Task, current_user: User, input_payload: dict | None) -> None:
    file_ids = input_payload.get("workspace_file_ids") if isinstance(input_payload, dict) else None
    if not isinstance(file_ids, list) or not file_ids:
        return

    normalized_ids: list[int] = []
    for file_id in file_ids:
        try:
            normalized_ids.append(int(file_id))
        except (TypeError, ValueError):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid workspace_file_ids")

    for file_id in normalized_ids:
        source_file = _get_accessible_task_file(db, file_id, current_user.id)
        task_file = TaskFile(
            task_id=task.id,
            user_id=current_user.id,
            workspace_id=task.workspace_id,
            filename=source_file.filename,
            storage_key=source_file.storage_key,
            mime_type=source_file.mime_type,
            size=source_file.size,
            source="workspace_reference",
        )
        db.add(task_file)
        db.commit()
        db.refresh(task_file)

        if DISPATCH_AGENT_TASKS:
            data = storage.read(source_file.storage_key)
            transfer = await transfer_file_to_agentsdk(
                task.id,
                task_file.filename,
                data,
                task_file.content_type,
                task_file.filename,
                task.workspace.root_path if task.workspace else None,
            )
            if transfer:
                await EventService(db).create_event(
                    task.id,
                    "file_saved",
                    task_file.filename,
                    {"file_id": task_file.id, "sandbox_path": transfer.get("path"), "source": "workspace_reference"},
                )
            else:
                await EventService(db).create_event(
                    task.id,
                    "tool_call_failed",
                    task_file.filename,
                    {"file_id": task_file.id, "source": "workspace_reference"},
                )


@router.post("", response_model=TaskCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    task_in: TaskCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_active_workspace(db, current_user)
    workspace_id = task_in.workspace_id if task_in.workspace_id is not None else current_user.active_workspace_id
    if workspace_id is not None:
        workspace = get_workspace_for_member(db, workspace_id, current_user.id)
        if not workspace:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    agent_type = task_in.agent_type or task_in.runtime or "hermes_acp"
    runtime = task_in.runtime or agent_type
    title = task_in.title or task_in.prompt[:80]
    task_input = _enrich_follow_up_input(db, task_in.input or {}, current_user.id)
    task = Task(
        owner_id=current_user.id,
        workspace_id=workspace_id,
        title=title,
        prompt=task_in.prompt,
        runtime=runtime,
        agent_type=agent_type,
        model=task_in.model or "default",
        input=encode_json(task_input),
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    await _attach_workspace_files_to_task(db, task, current_user, task_input)
    await EventService(db).create_event(task.id, "task_created", "任务已创建", {"status": "pending"})

    if task_in.dispatch:
        await set_task_status(db, task, "queued")

    if task_in.dispatch and DISPATCH_AGENT_TASKS:
        background_tasks.add_task(dispatch_task_to_agentsdk, task.id)

    return TaskCreateResponse(id=task.id, task_id=task.id, status=task.status)


@router.post("/{task_id}/start", response_model=TaskStartResponse)
async def start_task(
    task_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _get_accessible_task(db, task_id, current_user.id)
    if task.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task is not pending")
    await set_task_status(db, task, "queued")
    if DISPATCH_AGENT_TASKS:
        background_tasks.add_task(dispatch_task_to_agentsdk, task.id)
    return TaskStartResponse(task_id=task.id, status=task.status)


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return task_to_response(_get_accessible_task(db, task_id, current_user.id))


@router.get("/{task_id}/events", response_model=TaskEventPage)
def list_task_events(
    task_id: int,
    after_seq: int = 0,
    after_event_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _get_accessible_task(db, task_id, current_user.id)
    if after_event_id is not None:
        cursor_event = db.query(TaskEvent).filter(TaskEvent.id == after_event_id, TaskEvent.task_id == task_id).first()
        if cursor_event:
            after_seq = cursor_event.seq
    events = db.query(TaskEvent).filter(TaskEvent.task_id == task_id, TaskEvent.seq > after_seq).order_by(TaskEvent.seq.asc()).limit(limit + 1).all()
    has_more = len(events) > limit
    items = [event_to_response(event) for event in events[:limit]]
    return TaskEventPage(items=items, next_cursor=str(items[-1].id) if has_more and items else None)


@router.post("/{task_id}/cancel", response_model=TaskCancelResponse)
async def cancel_task(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = _get_accessible_task(db, task_id, current_user.id)
    if task.status in {"completed", "failed", "cancelled"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task is already terminal")
    await set_task_status(db, task, "cancelling", "正在取消任务")
    await set_task_status(db, task, "cancelled", "任务已取消")
    return TaskCancelResponse(task_id=task.id, status=task.status)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = _get_accessible_task(db, task_id, current_user.id)
    if task.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only task owner can delete task")
    if task.status in {"queued", "running", "waiting_approval", "cancelling"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Running task cannot be deleted")

    task_files = db.query(TaskFile).filter(TaskFile.task_id == task_id).all()
    workspace_root_path = task.workspace.root_path if task.workspace else None
    _cleanup_task_files(db, task_files)
    db.delete(task)
    db.commit()
    await cleanup_task_sandbox_from_agentsdk(task_id, workspace_root_path)
    return None


@router.get("/{task_id}/approvals", response_model=list[ApprovalResponse])
def list_task_approvals(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_accessible_task(db, task_id, current_user.id)
    approvals = db.query(TaskApproval).filter(TaskApproval.task_id == task_id).order_by(TaskApproval.created_at.asc()).all()
    return [_approval_response(approval) for approval in approvals]


def _get_accessible_task_approval(db: Session, task_id: int, approval_id: int, user_id: int) -> TaskApproval:
    _get_accessible_task(db, task_id, user_id)
    approval = db.query(TaskApproval).filter(TaskApproval.id == approval_id, TaskApproval.task_id == task_id).first()
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return approval


@router.post("/{task_id}/approvals/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_task_approval(
    task_id: int,
    approval_id: int,
    decision: ApprovalDecision | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approval = _get_accessible_task_approval(db, task_id, approval_id, current_user.id)
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval already decided")
    approval.status = "approved"
    approval.response = json.dumps((decision.response if decision else None) or {}, ensure_ascii=False)
    approval.resolved_at = datetime.utcnow()
    approval.resolved_by = current_user.id
    db.commit()
    db.refresh(approval)
    task = _get_accessible_task(db, task_id, current_user.id)
    if task.status == "waiting_approval":
        await set_task_status(db, task, "running", "审批已通过，任务继续执行")
    await EventService(db).create_event(task_id, "approval_approved", approval.action, {"approval_id": approval.id})
    return _approval_response(approval)


@router.post("/{task_id}/approvals/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_task_approval(
    task_id: int,
    approval_id: int,
    decision: ApprovalDecision | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approval = _get_accessible_task_approval(db, task_id, approval_id, current_user.id)
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval already decided")
    approval.status = "rejected"
    approval.response = json.dumps((decision.response if decision else None) or {}, ensure_ascii=False)
    approval.resolved_at = datetime.utcnow()
    approval.resolved_by = current_user.id
    db.commit()
    db.refresh(approval)
    await EventService(db).create_event(task_id, "approval_rejected", approval.action, {"approval_id": approval.id})
    return _approval_response(approval)
