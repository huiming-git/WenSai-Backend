from app.users.models import User
from app.workspaces.models import Workspace, WorkspaceMember
from conftest import TestingSessionLocal


def test_register_creates_default_workspace(client):
    resp = client.post(
        "/api/auth/register",
        json={"username": "spaceuser", "password": "testpass123", "invite_code": "huiming"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["active_workspace_id"] is not None
    assert data["active_workspace"]["name"] == "个人空间"
    assert data["active_workspace"]["invite_code"]

    spaces_resp = client.post("/api/auth/login", json={"username": "spaceuser", "password": "testpass123"})
    assert spaces_resp.status_code == 200
    spaces_headers = {"Authorization": f"Bearer {spaces_resp.json()['access_token']}"}
    list_resp = client.get("/api/workspaces", headers=spaces_headers)
    assert list_resp.status_code == 200
    spaces = list_resp.json()
    assert len(spaces) == 1
    assert spaces[0]["name"] == "个人空间"
    assert spaces[0]["root_path"]


def test_list_workspaces_auto_creates_missing_local_workspace(client, auth_headers):
    db = TestingSessionLocal()
    try:
        user = db.query(User).filter(User.username == "testuser").first()
        assert user is not None
        memberships = db.query(WorkspaceMember).filter(WorkspaceMember.user_id == user.id).all()
        for membership in memberships:
            db.delete(membership)
        owned_workspaces = db.query(Workspace).filter(Workspace.owner_id == user.id).all()
        for workspace in owned_workspaces:
            db.delete(workspace)
        user.active_workspace_id = None
        db.add(user)
        db.commit()
    finally:
        db.close()

    resp = client.get("/api/workspaces", headers=auth_headers)
    assert resp.status_code == 200
    workspaces = resp.json()
    assert len(workspaces) == 1
    assert workspaces[0]["name"] == "个人空间"
    assert workspaces[0]["root_path"]


def test_user_can_join_and_switch_workspaces(client, auth_headers, second_user_headers):
    owner_me = client.get("/api/auth/me", headers=auth_headers)
    invite_code = owner_me.json()["active_workspace"]["invite_code"]

    join_resp = client.post("/api/workspaces/join", json={"invite_code": invite_code}, headers=second_user_headers)
    assert join_resp.status_code == 200
    joined = join_resp.json()
    assert joined["invite_code"] == invite_code
    assert joined["is_active"] is True

    list_resp = client.get("/api/workspaces", headers=second_user_headers)
    assert list_resp.status_code == 200
    workspaces = list_resp.json()
    assert len(workspaces) == 2
    own_workspace = next(item for item in workspaces if item["role"] == "owner")

    switch_resp = client.post(f"/api/workspaces/{own_workspace['id']}/switch", headers=second_user_headers)
    assert switch_resp.status_code == 200
    assert switch_resp.json()["active_workspace_id"] == own_workspace["id"]


def test_workspace_member_can_access_shared_task_and_files(client, auth_headers, second_user_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    async def stub_transfer(task_id: int, filename: str, data: bytes, content_type: str | None = None, relative_path: str | None = None, workspace_root_path: str | None = None):
        return {"path": f"/sandbox/input/{relative_path or filename}"}

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.files.router.transfer_file_to_agentsdk", stub_transfer)

    owner_me = client.get("/api/auth/me", headers=auth_headers)
    invite_code = owner_me.json()["active_workspace"]["invite_code"]

    create_resp = client.post(
        "/api/tasks",
        json={"title": "Shared task", "prompt": "workspace collaboration", "dispatch": False},
        headers=auth_headers,
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]

    upload_resp = client.post(
        f"/api/tasks/{task_id}/files",
        data={"relative_path": "shared/input.txt"},
        files={"file": ("input.txt", b"hello", "text/plain")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201

    join_resp = client.post("/api/workspaces/join", json={"invite_code": invite_code}, headers=second_user_headers)
    assert join_resp.status_code == 200

    task_resp = client.get(f"/api/tasks/{task_id}", headers=second_user_headers)
    assert task_resp.status_code == 200
    assert task_resp.json()["workspace_id"] == owner_me.json()["active_workspace_id"]

    files_resp = client.get(f"/api/tasks/{task_id}/files", headers=second_user_headers)
    assert files_resp.status_code == 200
    assert len(files_resp.json()) == 1


def test_workspace_owner_can_list_members_remove_member_and_list_tasks(client, auth_headers, second_user_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)

    owner_me = client.get("/api/auth/me", headers=auth_headers)
    workspace_id = owner_me.json()["active_workspace_id"]
    invite_code = owner_me.json()["active_workspace"]["invite_code"]

    join_resp = client.post("/api/workspaces/join", json={"invite_code": invite_code}, headers=second_user_headers)
    assert join_resp.status_code == 200

    task_resp = client.post(
        "/api/tasks",
        json={"title": "Workspace timeline", "prompt": "collect workspace tasks", "dispatch": False},
        headers=auth_headers,
    )
    assert task_resp.status_code == 201

    members_resp = client.get(f"/api/workspaces/{workspace_id}/members", headers=auth_headers)
    assert members_resp.status_code == 200
    members = members_resp.json()
    assert len(members) == 2
    removable = next(member for member in members if member["role"] != "owner")

    tasks_resp = client.get(f"/api/workspaces/{workspace_id}/tasks", headers=auth_headers)
    assert tasks_resp.status_code == 200
    tasks = tasks_resp.json()
    assert len(tasks) == 1
    assert tasks[0]["title"] == "Workspace timeline"

    remove_resp = client.delete(
        f"/api/workspaces/{workspace_id}/members/{removable['user_id']}",
        headers=auth_headers,
    )
    assert remove_resp.status_code == 204

    members_resp = client.get(f"/api/workspaces/{workspace_id}/members", headers=auth_headers)
    assert members_resp.status_code == 200
    assert len(members_resp.json()) == 1


def test_workspace_owner_can_delete_team_workspace_and_fallback_to_local(client, auth_headers, second_user_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)

    create_space = client.post("/api/workspaces", json={"name": "项目协作空间"}, headers=auth_headers)
    assert create_space.status_code == 201
    workspace = create_space.json()
    workspace_id = workspace["id"]

    join_resp = client.post("/api/workspaces/join", json={"invite_code": workspace["invite_code"]}, headers=second_user_headers)
    assert join_resp.status_code == 200

    task_resp = client.post(
        "/api/tasks",
        json={"title": "Workspace task", "prompt": "keep my files", "dispatch": False},
        headers=auth_headers,
    )
    assert task_resp.status_code == 201
    task_id = task_resp.json()["id"]

    delete_resp = client.delete(f"/api/workspaces/{workspace_id}", headers=auth_headers)
    assert delete_resp.status_code == 204

    owner_spaces = client.get("/api/workspaces", headers=auth_headers)
    assert owner_spaces.status_code == 200
    owner_workspaces = owner_spaces.json()
    assert len(owner_workspaces) == 1
    assert owner_workspaces[0]["name"] == "个人空间"

    owner_me = client.get("/api/auth/me", headers=auth_headers)
    assert owner_me.status_code == 200
    assert owner_me.json()["active_workspace"]["name"] == "个人空间"

    task_detail = client.get(f"/api/tasks/{task_id}", headers=auth_headers)
    assert task_detail.status_code == 200
    assert task_detail.json()["workspace_id"] == owner_workspaces[0]["id"]

    second_me = client.get("/api/auth/me", headers=second_user_headers)
    assert second_me.status_code == 200
    assert second_me.json()["active_workspace"]["name"] == "个人空间"
