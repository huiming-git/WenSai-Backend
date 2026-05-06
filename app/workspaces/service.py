import secrets
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import LOCAL_WORKSPACE_ROOT
from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceMember

LOCAL_WORKSPACE_NAME = "个人空间"
LEGACY_LOCAL_WORKSPACE_NAMES = {"本地空间", "个人空间"}


def generate_invite_code(db: Session) -> str:
    while True:
        code = secrets.token_hex(4).upper()
        existing = db.query(Workspace.id).filter(Workspace.invite_code == code).first()
        if not existing:
            return code


def create_workspace_for_user(db: Session, owner: User, name: str) -> Workspace:
    workspace = Workspace(owner_id=owner.id, name=name.strip(), invite_code=generate_invite_code(db))
    db.add(workspace)
    db.flush()
    ensure_workspace_root_path(db, workspace)
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner"))
    return workspace


def build_local_workspace_root(owner_id: int, workspace_id: int) -> str:
    return str((Path(LOCAL_WORKSPACE_ROOT) / f"user-{owner_id}" / f"workspace-{workspace_id}").resolve())


def ensure_workspace_root_path(db: Session, workspace: Workspace | None) -> bool:
    if workspace is None or workspace.root_path:
        return False
    if workspace.name.strip() not in LEGACY_LOCAL_WORKSPACE_NAMES:
        return False
    workspace.root_path = build_local_workspace_root(workspace.owner_id, workspace.id or 0)
    Path(workspace.root_path).mkdir(parents=True, exist_ok=True)
    db.add(workspace)
    db.flush()
    return True


def ensure_local_workspace(db: Session, user: User) -> Workspace:
    workspace = (
        db.query(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(
            WorkspaceMember.user_id == user.id,
            Workspace.owner_id == user.id,
            Workspace.name.in_(LEGACY_LOCAL_WORKSPACE_NAMES),
        )
        .order_by(Workspace.created_at.asc(), Workspace.id.asc())
        .first()
    )
    if workspace is None:
        workspace = create_workspace_for_user(db, user, LOCAL_WORKSPACE_NAME)
        if user.active_workspace_id is None:
            user.active_workspace_id = workspace.id
        db.add(user)
        db.commit()
        db.refresh(user)
        db.refresh(workspace)
        return workspace

    mutated = False
    if workspace.name != LOCAL_WORKSPACE_NAME:
        workspace.name = LOCAL_WORKSPACE_NAME
        db.add(workspace)
        mutated = True
    if ensure_workspace_root_path(db, workspace):
        mutated = True
    if mutated:
        db.commit()
        db.refresh(workspace)
    return workspace


def get_workspace_for_member(db: Session, workspace_id: int, user_id: int) -> Workspace | None:
    return (
        db.query(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(Workspace.id == workspace_id, WorkspaceMember.user_id == user_id)
        .first()
    )


def get_workspace_membership(db: Session, workspace_id: int, user_id: int) -> WorkspaceMember | None:
    return (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
        .first()
    )


def ensure_active_workspace(db: Session, user: User) -> Workspace | None:
    ensure_local_workspace(db, user)

    if user.active_workspace_id is not None:
        active_workspace = get_workspace_for_member(db, user.active_workspace_id, user.id)
        if active_workspace:
            if ensure_workspace_root_path(db, active_workspace):
                db.commit()
                db.refresh(active_workspace)
            return active_workspace

    membership = (
        db.query(WorkspaceMember)
        .filter(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at.asc(), WorkspaceMember.id.asc())
        .first()
    )
    if not membership:
        return None

    user.active_workspace_id = membership.workspace_id
    db.add(user)
    db.commit()
    db.refresh(user)
    workspace = get_workspace_for_member(db, membership.workspace_id, user.id)
    if ensure_workspace_root_path(db, workspace):
        db.commit()
        db.refresh(workspace)
    return workspace


def count_workspace_members(db: Session, workspace_ids: list[int]) -> dict[int, int]:
    if not workspace_ids:
        return {}
    rows = (
        db.query(WorkspaceMember.workspace_id, func.count(WorkspaceMember.id))
        .filter(WorkspaceMember.workspace_id.in_(workspace_ids))
        .group_by(WorkspaceMember.workspace_id)
        .all()
    )
    return {workspace_id: member_count for workspace_id, member_count in rows}
