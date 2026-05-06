from app.config import INTERNAL_API_TOKEN
from app.tasks.dispatcher import redispatch_queued_tasks
from app.tasks.models import Task
from app.tasks.service import set_task_status
from conftest import TestingSessionLocal


def test_create_task_and_internal_event_flow(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)

    resp = client.post(
        "/api/tasks",
        json={"title": "Analyze repo", "prompt": "inspect code", "runtime": "hermes-acp"},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task = resp.json()
    assert task["status"] == "queued"

    detail_resp = client.get(f"/api/tasks/{task['id']}", headers=auth_headers)
    assert detail_resp.status_code == 200
    assert detail_resp.json()["workspace_root_path"]

    internal_headers = {"X-Internal-Token": INTERNAL_API_TOKEN}
    resp = client.post(f"/api/internal/tasks/{task['id']}/status", json={"status": "running"}, headers=internal_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "running"

    resp = client.post(
        f"/api/internal/tasks/{task['id']}/events",
        json={"type": "agent_message", "content": "hello", "metadata": {"x": 1}},
        headers=internal_headers,
    )
    assert resp.status_code == 200

    resp = client.get(f"/api/tasks/{task['id']}/events", headers=auth_headers)
    assert resp.status_code == 200
    events = resp.json()["items"]
    assert events[-1]["type"] == "agent_message"
    assert events[-1]["metadata"] == {"x": 1}

    resp = client.post(
        f"/api/internal/tasks/{task['id']}/result",
        json={"status": "completed", "result": "done"},
        headers=internal_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["result"] == "done"


def test_internal_approval_and_user_decision(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    task = client.post(
        "/api/tasks",
        json={"title": "Needs approval", "prompt": "edit file"},
        headers=auth_headers,
    ).json()

    resp = client.post(
        f"/api/internal/tasks/{task['id']}/approvals",
        json={"action": "Edit config", "risk": "high", "payload": {"path": "config.yml"}},
        headers={"X-Internal-Token": INTERNAL_API_TOKEN},
    )
    assert resp.status_code == 201
    approval = resp.json()
    assert approval["status"] == "pending"

    resp = client.post(
        f"/api/approvals/{approval['id']}/approve",
        json={"response": {"reason": "ok"}},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"

    resp = client.get(
        f"/api/internal/approvals/{approval['id']}",
        headers={"X-Internal-Token": INTERNAL_API_TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json()["response"] == {"reason": "ok"}


def test_task_file_upload_download_and_internal_archive(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    task = client.post(
        "/api/tasks",
        json={"title": "Files", "prompt": "produce output"},
        headers=auth_headers,
    ).json()

    resp = client.post(
        f"/api/tasks/{task['id']}/files",
        files={"file": ("input.txt", b"input", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 201

    resp = client.post(
        f"/api/internal/tasks/{task['id']}/files",
        files={"file": ("output.txt", b"output", "text/plain")},
        headers={"X-Internal-Token": INTERNAL_API_TOKEN},
    )
    assert resp.status_code == 201
    file_id = resp.json()["id"]

    resp = client.get(f"/api/tasks/{task['id']}/files", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2

    resp = client.get(f"/api/files/{file_id}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.content == b"output"


def test_delete_task_file_deletes_real_agentsdk_sandbox_file(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    deleted: list[tuple[int, str, str, str | None]] = []

    async def stub_delete(task_id: int, relative_path: str, area: str = "input", workspace_root_path: str | None = None):
        deleted.append((task_id, relative_path, area, workspace_root_path))
        return True

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.files.router.delete_file_from_agentsdk_sandbox", stub_delete)

    task = client.post(
        "/api/tasks",
        json={"title": "Delete file", "prompt": "delete file", "dispatch": False},
        headers=auth_headers,
    ).json()
    upload_resp = client.post(
        f"/api/tasks/{task['id']}/files",
        data={"relative_path": "docs/delete-me.txt"},
        files={"file": ("delete-me.txt", b"delete me", "text/plain")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    file_id = upload_resp.json()["id"]

    detail_resp = client.get(f"/api/tasks/{task['id']}", headers=auth_headers)
    workspace_root_path = detail_resp.json()["workspace_root_path"]

    delete_resp = client.delete(f"/api/files/{file_id}", headers=auth_headers)

    assert delete_resp.status_code == 204
    assert deleted == [(task["id"], "docs/delete-me.txt", "input", workspace_root_path)]
    list_resp = client.get(f"/api/tasks/{task['id']}/files", headers=auth_headers)
    assert list_resp.status_code == 200
    assert list_resp.json() == []


def test_delete_task_file_fails_when_agentsdk_sandbox_delete_fails(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    async def stub_delete(task_id: int, relative_path: str, area: str = "input", workspace_root_path: str | None = None):
        return False

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.files.router.delete_file_from_agentsdk_sandbox", stub_delete)

    task = client.post(
        "/api/tasks",
        json={"title": "Delete file", "prompt": "delete file", "dispatch": False},
        headers=auth_headers,
    ).json()
    upload_resp = client.post(
        f"/api/tasks/{task['id']}/files",
        files={"file": ("keep-me.txt", b"keep me", "text/plain")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    file_id = upload_resp.json()["id"]

    delete_resp = client.delete(f"/api/files/{file_id}", headers=auth_headers)

    assert delete_resp.status_code == 502
    list_resp = client.get(f"/api/tasks/{task['id']}/files", headers=auth_headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 1


def test_delete_agent_output_file_deletes_output_area(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    deleted: list[tuple[int, str, str, str | None]] = []

    async def stub_delete(task_id: int, relative_path: str, area: str = "input", workspace_root_path: str | None = None):
        deleted.append((task_id, relative_path, area, workspace_root_path))
        return True

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.files.router.delete_file_from_agentsdk_sandbox", stub_delete)

    task = client.post(
        "/api/tasks",
        json={"title": "Output file", "prompt": "output file", "dispatch": False},
        headers=auth_headers,
    ).json()
    archive_resp = client.post(
        f"/api/internal/tasks/{task['id']}/files",
        files={"file": ("result.md", b"done", "text/markdown")},
        headers={"X-Internal-Token": INTERNAL_API_TOKEN},
    )
    assert archive_resp.status_code == 201
    file_id = archive_resp.json()["id"]
    detail_resp = client.get(f"/api/tasks/{task['id']}", headers=auth_headers)
    workspace_root_path = detail_resp.json()["workspace_root_path"]

    delete_resp = client.delete(f"/api/files/{file_id}", headers=auth_headers)

    assert delete_resp.status_code == 204
    assert deleted == [(task["id"], "result.md", "output", workspace_root_path)]


def test_delete_task_cleans_storage_preview_and_agentsdk_sandbox(client, auth_headers, monkeypatch, tmp_path):
    async def stub_dispatch(task_id: int):
        return None

    cleaned: list[tuple[int, str | None]] = []

    async def stub_cleanup(task_id: int, workspace_root_path: str | None = None):
        cleaned.append((task_id, workspace_root_path))

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.tasks.router.cleanup_task_sandbox_from_agentsdk", stub_cleanup)
    monkeypatch.setattr("app.tasks.router.PREVIEW_CACHE_DIR", str(tmp_path / "preview-cache"))

    task = client.post(
        "/api/tasks",
        json={"title": "Delete me", "prompt": "cleanup", "dispatch": False},
        headers=auth_headers,
    ).json()

    upload_resp = client.post(
        f"/api/tasks/{task['id']}/files",
        files={"file": ("delete-me.txt", b"delete me", "text/plain")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    file_payload = upload_resp.json()
    storage_key = file_payload["storage_key"]
    preview_dir = tmp_path / "preview-cache" / f"file-{file_payload['id']}"
    preview_dir.mkdir(parents=True)
    (preview_dir / "page-1.png").write_bytes(b"preview")

    from app.tasks.router import storage

    assert storage.exists(storage_key)
    assert preview_dir.exists()

    detail_resp = client.get(f"/api/tasks/{task['id']}", headers=auth_headers)
    assert detail_resp.status_code == 200
    workspace_root_path = detail_resp.json()["workspace_root_path"]

    delete_resp = client.delete(f"/api/tasks/{task['id']}", headers=auth_headers)
    assert delete_resp.status_code == 204
    assert not storage.exists(storage_key)
    assert not preview_dir.exists()
    assert cleaned == [(task["id"], workspace_root_path)]


def test_delete_task_keeps_storage_shared_by_workspace_reference(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    async def stub_transfer(task_id: int, filename: str, data: bytes, content_type: str | None = None, relative_path: str | None = None, workspace_root_path: str | None = None):
        return {"path": f"/sandbox/input/{relative_path or filename}"}

    async def stub_cleanup(task_id: int, workspace_root_path: str | None = None):
        return None

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.tasks.router.transfer_file_to_agentsdk", stub_transfer)
    monkeypatch.setattr("app.files.router.transfer_file_to_agentsdk", stub_transfer)
    monkeypatch.setattr("app.tasks.router.cleanup_task_sandbox_from_agentsdk", stub_cleanup)

    source_task = client.post(
        "/api/tasks",
        json={"title": "Source", "prompt": "source file", "dispatch": False},
        headers=auth_headers,
    ).json()

    upload_resp = client.post(
        f"/api/tasks/{source_task['id']}/files",
        data={"relative_path": "docs/shared.txt"},
        files={"file": ("shared.txt", b"shared", "text/plain")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    source_file_id = upload_resp.json()["id"]

    referenced_task = client.post(
        "/api/tasks",
        json={
            "title": "Reference",
            "prompt": "use shared file",
            "dispatch": False,
            "input": {"workspace_file_ids": [source_file_id]},
        },
        headers=auth_headers,
    ).json()

    delete_resp = client.delete(f"/api/tasks/{referenced_task['id']}", headers=auth_headers)
    assert delete_resp.status_code == 204

    download_resp = client.get(f"/api/files/{source_file_id}", headers=auth_headers)
    assert download_resp.status_code == 200
    assert download_resp.content == b"shared"


def test_workspace_file_list_and_text_preview(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    async def stub_transfer(task_id: int, filename: str, data: bytes, content_type: str | None = None, relative_path: str | None = None, workspace_root_path: str | None = None):
        return {"path": f"/sandbox/input/{relative_path or filename}"}

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.files.router.transfer_file_to_agentsdk", stub_transfer)

    task = client.post(
        "/api/tasks",
        json={"title": "Workspace files", "prompt": "preview files", "dispatch": False},
        headers=auth_headers,
    ).json()

    upload_resp = client.post(
        f"/api/tasks/{task['id']}/files",
        data={"relative_path": "docs/readme.txt"},
        files={"file": ("readme.txt", b"workspace preview text", "text/plain")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    file_id = upload_resp.json()["id"]
    workspace_id = upload_resp.json()["workspace_id"]

    files_resp = client.get(f"/api/workspaces/{workspace_id}/files", headers=auth_headers)
    assert files_resp.status_code == 200
    files = files_resp.json()
    assert len(files) == 1
    assert files[0]["filename"] == "docs/readme.txt"

    preview_resp = client.get(f"/api/files/{file_id}/preview", headers=auth_headers)
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    assert preview["mode"] == "text"
    assert "workspace preview text" in preview["content"]


def test_pdf_preview_returns_gallery_pages(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    async def stub_transfer(task_id: int, filename: str, data: bytes, content_type: str | None = None, relative_path: str | None = None, workspace_root_path: str | None = None):
        return {"path": f"/sandbox/input/{relative_path or filename}"}

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.files.router.transfer_file_to_agentsdk", stub_transfer)

    task = client.post(
        "/api/tasks",
        json={"title": "PDF preview", "prompt": "preview pdf", "dispatch": False},
        headers=auth_headers,
    ).json()

    pdf_bytes = b"""%PDF-1.4
1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj
2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj
3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >> endobj
4 0 obj << /Length 44 >> stream
BT /F1 18 Tf 36 120 Td (Hello PDF Preview) Tj ET
endstream endobj
5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj
xref
0 6
0000000000 65535 f
0000000010 00000 n
0000000060 00000 n
0000000117 00000 n
0000000207 00000 n
0000000301 00000 n
trailer << /Root 1 0 R /Size 6 >>
startxref
371
%%EOF"""

    upload_resp = client.post(
        f"/api/tasks/{task['id']}/files",
        data={"relative_path": "docs/preview.pdf"},
        files={"file": ("preview.pdf", pdf_bytes, "application/pdf")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    file_id = upload_resp.json()["id"]

    preview_resp = client.get(f"/api/files/{file_id}/preview", headers=auth_headers)
    assert preview_resp.status_code == 200
    preview = preview_resp.json()
    assert preview["mode"] == "gallery"
    assert preview["page_count"] >= 1
    assert preview["page_image_urls"]


def test_create_task_with_workspace_file_reference(client, auth_headers, monkeypatch):
    dispatched: list[int] = []
    transferred: list[tuple[int, str, str | None]] = []

    async def stub_dispatch(task_id: int):
        dispatched.append(task_id)

    async def stub_transfer(task_id: int, filename: str, data: bytes, content_type: str | None = None, relative_path: str | None = None, workspace_root_path: str | None = None):
        transferred.append((task_id, filename, relative_path))
        return {"path": f"/sandbox/input/{relative_path or filename}"}

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.tasks.router.transfer_file_to_agentsdk", stub_transfer)
    monkeypatch.setattr("app.files.router.transfer_file_to_agentsdk", stub_transfer)

    source_task = client.post(
        "/api/tasks",
        json={"title": "Source", "prompt": "source file", "dispatch": False},
        headers=auth_headers,
    ).json()

    upload_resp = client.post(
        f"/api/tasks/{source_task['id']}/files",
        data={"relative_path": "slides/demo.md"},
        files={"file": ("demo.md", b"# demo", "text/markdown")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    source_file_id = upload_resp.json()["id"]

    new_task_resp = client.post(
        "/api/tasks",
        json={
            "title": "Referenced",
            "prompt": "use workspace file",
            "dispatch": False,
            "input": {"workspace_file_ids": [source_file_id]},
        },
        headers=auth_headers,
    )
    assert new_task_resp.status_code == 201
    new_task_id = new_task_resp.json()["id"]

    files_resp = client.get(f"/api/tasks/{new_task_id}/files", headers=auth_headers)
    assert files_resp.status_code == 200
    files = files_resp.json()
    assert len(files) == 1
    assert files[0]["filename"] == "slides/demo.md"
    assert files[0]["source"] == "workspace_reference"
    assert transferred[-1] == (new_task_id, "slides/demo.md", "slides/demo.md")


def test_follow_up_task_includes_parent_conversation_context(client, auth_headers, monkeypatch):
    async def stub_dispatch(task_id: int):
        return None

    transferred: list[tuple[int, str, str | None]] = []

    async def stub_transfer(task_id: int, filename: str, data: bytes, content_type: str | None = None, relative_path: str | None = None, workspace_root_path: str | None = None):
        transferred.append((task_id, filename, relative_path))
        return {"path": f"/sandbox/input/{relative_path or filename}"}

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.tasks.router.transfer_file_to_agentsdk", stub_transfer)
    monkeypatch.setattr("app.files.router.transfer_file_to_agentsdk", stub_transfer)

    parent_resp = client.post(
        "/api/tasks",
        json={"title": "Parent", "prompt": "上一轮问题", "dispatch": False},
        headers=auth_headers,
    )
    assert parent_resp.status_code == 201
    parent_id = parent_resp.json()["id"]

    complete_resp = client.post(
        f"/api/internal/tasks/{parent_id}/result",
        json={"message": "上一轮回答"},
        headers={"X-Internal-Token": INTERNAL_API_TOKEN},
    )
    assert complete_resp.status_code == 200

    upload_resp = client.post(
        f"/api/tasks/{parent_id}/files",
        data={"relative_path": "slides/demo.pptx"},
        files={"file": ("demo.pptx", b"ppt", "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=auth_headers,
    )
    assert upload_resp.status_code == 201
    parent_file_id = upload_resp.json()["id"]

    follow_resp = client.post(
        "/api/tasks",
        json={
            "title": "Follow",
            "prompt": "继续处理",
            "dispatch": False,
            "input": {"parent_task_id": parent_id},
        },
        headers=auth_headers,
    )
    assert follow_resp.status_code == 201
    detail_resp = client.get(f"/api/tasks/{follow_resp.json()['id']}", headers=auth_headers)
    task_input = detail_resp.json()["input"]
    assert task_input["parent_task_id"] == parent_id
    assert "上一轮问题" in task_input["conversation_context"]
    assert "上一轮回答" in task_input["conversation_context"]
    assert parent_file_id in task_input["workspace_file_ids"]
    assert transferred[-1] == (follow_resp.json()["id"], "slides/demo.pptx", "slides/demo.pptx")


def test_create_pending_upload_sandbox_file_then_start(client, auth_headers, monkeypatch):
    dispatched: list[int] = []
    transferred: list[tuple[int, str, str | None]] = []

    async def stub_dispatch(task_id: int):
        dispatched.append(task_id)

    async def stub_transfer(task_id: int, filename: str, data: bytes, content_type: str | None = None, relative_path: str | None = None, workspace_root_path: str | None = None):
        transferred.append((task_id, filename, relative_path))
        return {"path": f"/sandbox/input/{relative_path or filename}"}

    monkeypatch.setattr("app.tasks.router.dispatch_task_to_agentsdk", stub_dispatch)
    monkeypatch.setattr("app.files.router.transfer_file_to_agentsdk", stub_transfer)

    resp = client.post(
        "/api/tasks",
        json={"title": "Sandbox", "prompt": "inspect sandbox", "dispatch": False},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    task = resp.json()
    assert task["status"] == "pending"
    assert dispatched == []

    resp = client.post(
        f"/api/tasks/{task['id']}/files",
        data={"relative_path": "docs/input.txt"},
        files={"file": ("input.txt", b"input", "text/plain")},
        headers=auth_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["filename"] == "docs/input.txt"
    assert transferred == [(task["id"], "docs/input.txt", "docs/input.txt")]

    resp = client.post(f"/api/tasks/{task['id']}/start", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "queued"
    assert dispatched == [task["id"]]


def test_redispatch_queued_tasks_on_startup(client, auth_headers, monkeypatch):
    dispatched: list[int] = []

    async def stub_dispatch(task_id: int):
        dispatched.append(task_id)

    monkeypatch.setattr("app.tasks.dispatcher.dispatch_task_to_agentsdk", stub_dispatch)

    task = client.post(
        "/api/tasks",
        json={"title": "Queued task", "prompt": "resume me", "dispatch": False},
        headers=auth_headers,
    ).json()

    db = TestingSessionLocal()
    try:
        queued_task = db.query(Task).filter(Task.id == task["id"]).first()
        assert queued_task is not None
        import asyncio

        asyncio.run(set_task_status(db, queued_task, "queued"))
        redispatched = asyncio.run(redispatch_queued_tasks(db))
    finally:
        db.close()

    assert redispatched == [task["id"]]
    assert dispatched == [task["id"]]
