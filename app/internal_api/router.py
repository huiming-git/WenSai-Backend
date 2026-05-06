import json
import time

from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import INTERNAL_API_TOKEN
from app.dependencies import get_db
from app.approvals.models import TaskApproval
from app.approvals.schemas import ApprovalCreate, ApprovalResponse
from app.events.schemas import TaskEventCreate
from app.events.service import EventService
from app.files.models import TaskFile
from app.files.schemas import TaskFileResponse
from app.storage import storage
from app.tasks.models import Task
from app.tasks.schemas import TaskResponse
from app.tasks.service import encode_json, set_task_status, task_to_response
from app.internal_api.schemas import TaskErrorUpdate, TaskResultUpdate, TaskStatusUpdate

router = APIRouter(prefix="/api/internal", tags=["internal"])


def require_internal_token(x_internal_token: str | None = Header(default=None)) -> None:
    if x_internal_token != INTERNAL_API_TOKEN:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal token")


def _get_task(db: Session, task_id: int) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return task


def _decode(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


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


@router.get("/tasks/{task_id}", response_model=TaskResponse, dependencies=[Depends(require_internal_token)])
def get_task_for_agent(task_id: int, db: Session = Depends(get_db)):
    return task_to_response(_get_task(db, task_id))


@router.post("/tasks/{task_id}/status", response_model=TaskResponse, dependencies=[Depends(require_internal_token)])
async def update_task_status(task_id: int, update: TaskStatusUpdate, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    return await set_task_status(db, task, update.status)


@router.post("/tasks/{task_id}/events", dependencies=[Depends(require_internal_token)])
async def append_task_event(task_id: int, event: TaskEventCreate, db: Session = Depends(get_db)):
    _get_task(db, task_id)
    created = await EventService(db).create_event(
        task_id,
        event.type,
        event.content if event.content is not None else event.message,
        event.metadata if event.metadata is not None else event.payload,
    )
    return created


@router.post("/tasks/{task_id}/result", response_model=TaskResponse, dependencies=[Depends(require_internal_token)])
async def complete_task(task_id: int, update: TaskResultUpdate, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    result_payload = update.result if update.result is not None else {"message": update.message, "files": update.files or [], "metadata": update.metadata or {}}
    task.result = encode_json(result_payload)
    db.commit()
    db.refresh(task)
    await set_task_status(db, task, "completed", update.message or "任务完成")
    return task_to_response(task)


@router.post("/tasks/{task_id}/error", response_model=TaskResponse, dependencies=[Depends(require_internal_token)])
async def fail_task(task_id: int, update: TaskErrorUpdate, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    task.error = update.error
    db.commit()
    db.refresh(task)
    await set_task_status(db, task, "failed", update.error)
    return task_to_response(task)


@router.post("/tasks/{task_id}/approvals", response_model=ApprovalResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal_token)])
async def create_approval(task_id: int, approval_in: ApprovalCreate, db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    action_type = approval_in.action_type or approval_in.action or "agent.permission"
    risk_level = approval_in.risk_level or approval_in.risk or "medium"
    description = approval_in.description or approval_in.action or action_type
    approval = TaskApproval(
        task_id=task_id,
        action_type=action_type,
        risk_level=risk_level,
        description=description,
        payload=json.dumps(approval_in.payload, ensure_ascii=False) if approval_in.payload is not None else None,
    )
    db.add(approval)
    db.commit()
    db.refresh(approval)
    await set_task_status(db, task, "waiting_approval", "等待用户审批")
    await EventService(db).create_event(
        task_id,
        "approval_required",
        description,
        {"approval_id": approval.id, "action_type": action_type, "risk_level": risk_level, "payload": approval_in.payload or {}},
    )
    return _approval_response(approval)


@router.get("/approvals/{approval_id}", response_model=ApprovalResponse, dependencies=[Depends(require_internal_token)])
def get_approval_for_agent(approval_id: int, db: Session = Depends(get_db)):
    approval = db.query(TaskApproval).filter(TaskApproval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return _approval_response(approval)


@router.get("/approvals/{approval_id}/wait", response_model=ApprovalResponse, dependencies=[Depends(require_internal_token)])
def wait_approval_for_agent(approval_id: int, timeout: int = 3600, db: Session = Depends(get_db)):
    deadline = time.time() + min(timeout, 3600)
    while time.time() < deadline:
        approval = db.query(TaskApproval).filter(TaskApproval.id == approval_id).first()
        if not approval:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
        if approval.status != "pending":
            return _approval_response(approval)
        time.sleep(1)
        db.expire_all()
    approval = db.query(TaskApproval).filter(TaskApproval.id == approval_id).first()
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return _approval_response(approval)


@router.post("/tasks/{task_id}/files", response_model=TaskFileResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_internal_token)])
async def archive_task_file(task_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    task = _get_task(db, task_id)
    data = await file.read()
    key = storage.save(data, file.filename or "output.bin")
    task_file = TaskFile(
        task_id=task_id,
        user_id=task.owner_id,
        workspace_id=task.workspace_id,
        filename=file.filename or "output.bin",
        storage_key=key,
        mime_type=file.content_type,
        size=len(data),
        source="agent_output",
    )
    db.add(task_file)
    db.commit()
    db.refresh(task_file)
    await EventService(db).create_event(task_id, "file_saved", task_file.filename, {"file_id": task_file.id, "source": "agent_output"})
    return task_file
