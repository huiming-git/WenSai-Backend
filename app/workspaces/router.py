from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.files.models import TaskFile
from app.tasks.models import Task
from app.tasks.service import decode_json
from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceMember
from app.workspaces.schemas import (
    WorkspaceCreate,
    WorkspaceJoin,
    WorkspaceMemberResponse,
    WorkspaceResponse,
    WorkspaceSwitchResponse,
    WorkspaceTaskSummary,
)
from app.workspaces.service import (
    LOCAL_WORKSPACE_NAME,
    count_workspace_members,
    create_workspace_for_user,
    ensure_local_workspace,
    ensure_workspace_root_path,
    ensure_active_workspace,
    get_workspace_for_member,
    get_workspace_membership,
)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def _to_workspace_response(
    workspace: Workspace,
    active_workspace_id: int | None,
    member_counts: dict[int, int],
    membership_map: dict[int, WorkspaceMember],
) -> WorkspaceResponse:
    membership = membership_map.get(workspace.id)
    return WorkspaceResponse(
        id=workspace.id,
        owner_id=workspace.owner_id,
        name=workspace.name,
        invite_code=workspace.invite_code,
        role=membership.role if membership else "member",
        member_count=member_counts.get(workspace.id, 1),
        is_active=workspace.id == active_workspace_id,
        root_path=workspace.root_path,
        created_at=workspace.created_at,
    )


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    ensure_active_workspace(db, current_user)
    memberships = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == current_user.id)
        .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.id.asc())
        .all()
    )
    workspace_ids = [membership.workspace_id for membership in memberships]
    workspaces = (
        db.query(Workspace)
        .filter(Workspace.id.in_(workspace_ids))
        .order_by(Workspace.created_at.asc(), Workspace.id.asc())
        .all()
        if workspace_ids
        else []
    )
    mutated = False
    for workspace in workspaces:
        mutated = ensure_workspace_root_path(db, workspace) or mutated
    if mutated:
        db.commit()
        for workspace in workspaces:
            db.refresh(workspace)
    member_counts = count_workspace_members(db, workspace_ids)
    membership_map = {membership.workspace_id: membership for membership in memberships}
    return [
        _to_workspace_response(workspace, current_user.active_workspace_id, member_counts, membership_map)
        for workspace in workspaces
    ]


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
def create_workspace(payload: WorkspaceCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    workspace = create_workspace_for_user(db, current_user, payload.name)
    current_user.active_workspace_id = workspace.id
    db.add(current_user)
    db.commit()
    db.refresh(workspace)
    db.refresh(current_user)
    membership = get_workspace_membership(db, workspace.id, current_user.id)
    return _to_workspace_response(workspace, current_user.active_workspace_id, {workspace.id: 1}, {workspace.id: membership})


@router.post("/join", response_model=WorkspaceResponse)
def join_workspace(payload: WorkspaceJoin, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    invite_code = payload.invite_code.strip().upper()
    workspace = db.query(Workspace).filter(Workspace.invite_code == invite_code).first()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    membership = get_workspace_membership(db, workspace.id, current_user.id)
    if membership is None:
        membership = WorkspaceMember(workspace_id=workspace.id, user_id=current_user.id, role="member")
        db.add(membership)
    ensure_workspace_root_path(db, workspace)
    current_user.active_workspace_id = workspace.id
    db.add(current_user)
    db.commit()
    db.refresh(workspace)
    db.refresh(current_user)
    member_counts = count_workspace_members(db, [workspace.id])
    return _to_workspace_response(workspace, current_user.active_workspace_id, member_counts, {workspace.id: membership})


@router.post("/{workspace_id}/switch", response_model=WorkspaceSwitchResponse)
def switch_workspace(workspace_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    workspace = get_workspace_for_member(db, workspace_id, current_user.id)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    ensure_workspace_root_path(db, workspace)
    current_user.active_workspace_id = workspace.id
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return WorkspaceSwitchResponse(workspace_id=workspace.id, active_workspace_id=current_user.active_workspace_id)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(workspace_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    workspace = get_workspace_for_member(db, workspace_id, current_user.id)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if workspace.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only workspace owner can delete workspace")
    if workspace.name == LOCAL_WORKSPACE_NAME:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Local workspace cannot be deleted")

    local_workspace = ensure_local_workspace(db, current_user)

    affected_users = (
        db.query(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .all()
    )
    for user in affected_users:
        replacement = local_workspace if user.id == current_user.id else ensure_local_workspace(db, user)
        if user.active_workspace_id == workspace_id:
            user.active_workspace_id = replacement.id
            db.add(user)

    db.query(Task).filter(Task.workspace_id == workspace_id).update({Task.workspace_id: local_workspace.id}, synchronize_session=False)
    db.query(TaskFile).filter(TaskFile.workspace_id == workspace_id).update(
        {TaskFile.workspace_id: local_workspace.id},
        synchronize_session=False,
    )

    memberships = db.query(WorkspaceMember).filter(WorkspaceMember.workspace_id == workspace_id).all()
    for membership in memberships:
        db.delete(membership)

    db.delete(workspace)
    db.commit()
    return None


@router.get("/{workspace_id}/members", response_model=list[WorkspaceMemberResponse])
def list_workspace_members(workspace_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    workspace = get_workspace_for_member(db, workspace_id, current_user.id)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    memberships = (
        db.query(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .filter(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.id.asc())
        .all()
    )
    return [
        WorkspaceMemberResponse(
            id=membership.id,
            user_id=user.id,
            username=user.username,
            role=membership.role,
            created_at=membership.created_at,
        )
        for membership, user in memberships
    ]


@router.delete("/{workspace_id}/members/{member_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_workspace_member(
    workspace_id: int,
    member_user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workspace = get_workspace_for_member(db, workspace_id, current_user.id)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    if workspace.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only workspace owner can remove members")
    if member_user_id == workspace.owner_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Owner cannot be removed from workspace")

    membership = get_workspace_membership(db, workspace_id, member_user_id)
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    db.delete(membership)

    removed_user = db.query(User).filter(User.id == member_user_id).first()
    if removed_user and removed_user.active_workspace_id == workspace_id:
        replacement = (
            db.query(WorkspaceMember)
            .filter(WorkspaceMember.user_id == member_user_id, WorkspaceMember.workspace_id != workspace_id)
            .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.id.asc())
            .first()
        )
        removed_user.active_workspace_id = replacement.workspace_id if replacement else None
        db.add(removed_user)

    db.commit()
    return None


@router.get("/{workspace_id}/tasks", response_model=list[WorkspaceTaskSummary])
def list_workspace_tasks(workspace_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    workspace = get_workspace_for_member(db, workspace_id, current_user.id)
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")

    tasks = (
        db.query(Task, User)
        .join(User, User.id == Task.owner_id)
        .filter(Task.workspace_id == workspace_id)
        .order_by(Task.created_at.desc(), Task.id.desc())
        .all()
    )
    return [
        WorkspaceTaskSummary(
            id=task.id,
            owner_id=task.owner_id,
            owner_username=owner.username,
            workspace_id=task.workspace_id,
            title=task.title,
            prompt=task.prompt,
            status=task.status,
            agent_type=task.agent_type,
            input=decode_json(task.input),
            created_at=task.created_at,
        )
        for task, owner in tasks
    ]
