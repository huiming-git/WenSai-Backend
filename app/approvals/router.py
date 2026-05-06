import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.approvals.models import TaskApproval
from app.approvals.schemas import ApprovalDecision, ApprovalResponse
from app.events.service import EventService
from app.tasks.models import Task
from app.tasks.service import set_task_status
from app.users.models import User

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


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


def _get_owned_approval(db: Session, approval_id: int, user_id: int) -> TaskApproval:
    approval = (
        db.query(TaskApproval)
        .join(Task, Task.id == TaskApproval.task_id)
        .filter(TaskApproval.id == approval_id, Task.owner_id == user_id)
        .first()
    )
    if not approval:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return approval


@router.get("/{approval_id}", response_model=ApprovalResponse)
def get_approval(approval_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _approval_response(_get_owned_approval(db, approval_id, current_user.id))


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_approval(
    approval_id: int,
    decision: ApprovalDecision | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approval = _get_owned_approval(db, approval_id, current_user.id)
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval already decided")
    approval.status = "approved"
    approval.response = json.dumps((decision.response if decision else None) or {}, ensure_ascii=False)
    approval.resolved_at = datetime.utcnow()
    approval.resolved_by = current_user.id
    db.commit()
    db.refresh(approval)
    task = db.query(Task).filter(Task.id == approval.task_id).first()
    if task and task.status == "waiting_approval":
        await set_task_status(db, task, "running", "审批已通过，任务继续执行")
    await EventService(db).create_event(approval.task_id, "approval_approved", approval.action, {"approval_id": approval.id})
    return _approval_response(approval)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_approval(
    approval_id: int,
    decision: ApprovalDecision | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approval = _get_owned_approval(db, approval_id, current_user.id)
    if approval.status != "pending":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval already decided")
    approval.status = "rejected"
    approval.response = json.dumps((decision.response if decision else None) or {}, ensure_ascii=False)
    approval.resolved_at = datetime.utcnow()
    approval.resolved_by = current_user.id
    db.commit()
    db.refresh(approval)
    await EventService(db).create_event(approval.task_id, "approval_rejected", approval.action, {"approval_id": approval.id})
    return _approval_response(approval)


@router.get("/tasks/{task_id}/approvals", response_model=list[ApprovalResponse])
def list_task_approvals(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task = db.query(Task).filter(Task.id == task_id, Task.owner_id == current_user.id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    approvals = db.query(TaskApproval).filter(TaskApproval.task_id == task_id).order_by(TaskApproval.created_at.asc()).all()
    return [_approval_response(approval) for approval in approvals]


@router.post("/tasks/{task_id}/approvals/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_task_approval(
    task_id: int,
    approval_id: int,
    decision: ApprovalDecision | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approval = _get_owned_approval(db, approval_id, current_user.id)
    if approval.task_id != task_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return await approve_approval(approval_id, decision, db, current_user)


@router.post("/tasks/{task_id}/approvals/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_task_approval(
    task_id: int,
    approval_id: int,
    decision: ApprovalDecision | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    approval = _get_owned_approval(db, approval_id, current_user.id)
    if approval.task_id != task_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return await reject_approval(approval_id, decision, db, current_user)
