import hashlib
import mimetypes
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session
from xml.etree import ElementTree as ET

from app.config import DISPATCH_AGENT_TASKS, PDF_PREVIEW_DPI, PREVIEW_CACHE_DIR, SOFFICE_COMMAND
from app.dependencies import get_current_user, get_db
from app.events.service import create_task_event
from app.files.models import TaskFile
from app.files.schemas import FilePreviewResponse, TaskFileCreate, TaskFileResponse, WorkspaceFileResponse
from app.storage import storage
from app.tasks.dispatcher import delete_file_from_agentsdk_sandbox, transfer_file_to_agentsdk
from app.tasks.models import Task
from app.users.models import User
from app.workspaces.models import Workspace
from app.workspaces.models import WorkspaceMember

router = APIRouter(prefix="/api", tags=["task-files"])

TEXT_EXTENSIONS = {".txt", ".md", ".tex", ".csv", ".json", ".py", ".yaml", ".yml", ".toml", ".log"}
IMAGE_PREFIXES = ("image/",)
PDF_MIME_TYPES = {"application/pdf"}
DOCX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
PPTX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
XLSX_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
LEGACY_OFFICE_EXTENSIONS = {".doc", ".ppt", ".xls"}
OFFICE_EXTENSIONS = {".docx", ".pptx", ".xlsx", *LEGACY_OFFICE_EXTENSIONS}
FOLDER_MARKER_NAME = ".wensai-folder"


def _file_checksum(task_file: TaskFile) -> str:
    return hashlib.sha256(storage.read(task_file.storage_key)).hexdigest()


def _task_file_response(task_file: TaskFile) -> TaskFileResponse:
    return TaskFileResponse(
        id=task_file.id,
        user_id=task_file.user_id,
        workspace_id=task_file.workspace_id,
        task_id=task_file.task_id,
        filename=task_file.filename,
        mime_type=task_file.mime_type,
        content_type=task_file.content_type,
        size=task_file.size,
        checksum=_file_checksum(task_file),
        source=task_file.source,
        storage_key=task_file.storage_key,
        created_at=task_file.created_at,
    )


def _workspace_file_response(task_file: TaskFile) -> WorkspaceFileResponse:
    return WorkspaceFileResponse(
        id=task_file.id,
        user_id=task_file.user_id,
        workspace_id=task_file.workspace_id,
        task_id=task_file.task_id,
        filename=task_file.filename,
        mime_type=task_file.mime_type,
        size=task_file.size,
        checksum=_file_checksum(task_file),
        source=task_file.source,
        created_at=task_file.created_at,
    )


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
    return task


def _safe_relative_path(value: str | None, fallback: str) -> str:
    raw = (value or fallback or "upload.bin").replace("\\", "/").strip("/")
    parts = [part for part in PurePosixPath(raw).parts if part not in {"", ".", ".."}]
    return "/".join(parts) or Path(fallback or "upload.bin").name


def _get_accessible_workspace(db: Session, workspace_id: int, user_id: int) -> Workspace:
    workspace = (
        db.query(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(Workspace.id == workspace_id, WorkspaceMember.user_id == user_id)
        .first()
    )
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


def _get_accessible_file(db: Session, file_id: int, user_id: int) -> TaskFile:
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return task_file


def _folder_marker_path(folder_name: str) -> str:
    folder = _safe_relative_path(folder_name, "New Folder").rstrip("/")
    if not folder or folder == FOLDER_MARKER_NAME:
        folder = "New Folder"
    return f"{folder}/{FOLDER_MARKER_NAME}"


def _ensure_unique_task_filename(db: Session, task_id: int, filename: str) -> None:
    exists = db.query(TaskFile.id).filter(TaskFile.task_id == task_id, TaskFile.filename == filename).first()
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="File already exists")


def _extract_openxml_text(data: bytes, mode: str) -> str | None:
    try:
        with ZipFile(BytesIO(data)) as archive:
            xml_files: list[str]
            if mode == "docx":
                xml_files = ["word/document.xml"]
            elif mode == "pptx":
                xml_files = sorted(name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml"))
            elif mode == "xlsx":
                xml_files = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
            else:
                return None

            shared_strings: list[str] = []
            if mode == "xlsx" and "xl/sharedStrings.xml" in archive.namelist():
                root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
                namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                for item in root.findall("a:si", namespace):
                    shared_strings.append("".join(node.text or "" for node in item.iter() if node.text))

            chunks: list[str] = []
            for xml_file in xml_files:
                root = ET.fromstring(archive.read(xml_file))
                if mode == "xlsx":
                    namespace = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
                    rows: list[str] = []
                    for row in root.findall(".//a:row", namespace):
                        values: list[str] = []
                        for cell in row.findall("a:c", namespace):
                            raw_value = cell.findtext("a:v", default="", namespaces=namespace)
                            cell_type = cell.attrib.get("t")
                            if cell_type == "s" and raw_value.isdigit():
                                index = int(raw_value)
                                values.append(shared_strings[index] if index < len(shared_strings) else "")
                            else:
                                values.append(raw_value)
                        if any(values):
                            rows.append(" | ".join(value for value in values if value))
                    if rows:
                        chunks.append(f"[{Path(xml_file).stem}]\n" + "\n".join(rows))
                else:
                    text = "".join(node.text or "" for node in root.iter() if node.text)
                    if text.strip():
                        if mode == "pptx":
                            chunks.append(f"[{Path(xml_file).stem}]\n{text.strip()}")
                        else:
                            chunks.append(text.strip())
            combined = "\n\n".join(chunk for chunk in chunks if chunk.strip())
            return combined[:20000] if combined else None
    except Exception:
        return None


def _extract_pdf_text(pdf_path: Path) -> str | None:
    if not shutil.which("pdftotext"):
        return None

    text_path = pdf_path.with_suffix(".txt")
    if not text_path.exists():
        try:
            subprocess.run(["pdftotext", str(pdf_path), str(text_path)], check=True, capture_output=True)
        except subprocess.CalledProcessError:
            return None

    content = text_path.read_text(encoding="utf-8", errors="replace").strip()
    return content[:20000] if content else None


def _extract_office_text(task_file: TaskFile, data: bytes, converted_pdf: Path | None = None) -> str | None:
    suffix = Path(task_file.filename).suffix.lower()
    if suffix == ".docx":
        return _extract_openxml_text(data, "docx")
    if suffix == ".pptx":
        return _extract_openxml_text(data, "pptx")
    if suffix == ".xlsx":
        return _extract_openxml_text(data, "xlsx")
    if converted_pdf:
        return _extract_pdf_text(converted_pdf)
    return None


def _build_preview(task_file: TaskFile) -> FilePreviewResponse:
    data = storage.read(task_file.storage_key)
    checksum = hashlib.sha256(data).hexdigest()
    suffix = Path(task_file.filename).suffix.lower()
    mime_type = task_file.mime_type or "application/octet-stream"

    if mime_type.startswith(IMAGE_PREFIXES):
        return FilePreviewResponse(
            id=task_file.id,
            filename=task_file.filename,
            mime_type=mime_type,
            size=task_file.size,
            mode="image",
            download_url=f"/api/files/{task_file.id}/content",
        )
    if mime_type in PDF_MIME_TYPES or suffix == ".pdf":
        cache_was_valid = _is_preview_cache_valid(task_file, checksum)
        page_images = _render_pdf_preview(task_file, checksum)
        content = _extract_pdf_text(_ensure_source_copy(task_file))
        return FilePreviewResponse(
            id=task_file.id,
            filename=task_file.filename,
            mime_type=mime_type,
            size=task_file.size,
            mode="gallery",
            content=content,
            page_count=len(page_images),
            page_image_urls=[f"/api/files/{task_file.id}/preview/pages/{image.name}?v={checksum}" for image in page_images],
            download_url=f"/api/files/{task_file.id}/content",
            message=_preview_cache_message(cache_was_valid),
        )
    if suffix in TEXT_EXTENSIONS or mime_type.startswith("text/"):
        content = data.decode("utf-8", errors="replace")[:20000]
        return FilePreviewResponse(id=task_file.id, filename=task_file.filename, mime_type=mime_type, size=task_file.size, mode="text", content=content)
    if mime_type in DOCX_MIME_TYPES or suffix == ".docx":
        if shutil.which(SOFFICE_COMMAND):
            cache_was_valid = _is_preview_cache_valid(task_file, checksum)
            page_images = _render_office_preview(task_file, checksum)
            pdf_path = _convert_office_to_pdf(task_file)
            return FilePreviewResponse(
                id=task_file.id,
                filename=task_file.filename,
                mime_type=mime_type,
                size=task_file.size,
                mode="gallery",
                content=_extract_office_text(task_file, data, pdf_path),
                page_count=len(page_images),
                page_image_urls=[f"/api/files/{task_file.id}/preview/pages/{image.name}?v={checksum}" for image in page_images],
                download_url=f"/api/files/{task_file.id}/content",
                message=_preview_cache_message(cache_was_valid),
            )
        content = _extract_openxml_text(data, "docx")
        return FilePreviewResponse(
            id=task_file.id,
            filename=task_file.filename,
            mime_type=mime_type,
            size=task_file.size,
            mode="text",
            content=content or "无法提取该 Word 文件的文本预览。",
            download_url=f"/api/files/{task_file.id}/content",
            message="当前环境未安装 LibreOffice，已回退为文本预览。",
        )
    if mime_type in PPTX_MIME_TYPES or suffix == ".pptx":
        if shutil.which(SOFFICE_COMMAND):
            cache_was_valid = _is_preview_cache_valid(task_file, checksum)
            page_images = _render_office_preview(task_file, checksum)
            pdf_path = _convert_office_to_pdf(task_file)
            return FilePreviewResponse(
                id=task_file.id,
                filename=task_file.filename,
                mime_type=mime_type,
                size=task_file.size,
                mode="gallery",
                content=_extract_office_text(task_file, data, pdf_path),
                page_count=len(page_images),
                page_image_urls=[f"/api/files/{task_file.id}/preview/pages/{image.name}?v={checksum}" for image in page_images],
                download_url=f"/api/files/{task_file.id}/content",
                message=_preview_cache_message(cache_was_valid),
            )
        content = _extract_openxml_text(data, "pptx")
        return FilePreviewResponse(
            id=task_file.id,
            filename=task_file.filename,
            mime_type=mime_type,
            size=task_file.size,
            mode="text",
            content=content or "无法提取该 PPT 文件的文本预览。",
            download_url=f"/api/files/{task_file.id}/content",
            message="当前环境未安装 LibreOffice，已回退为文本预览。",
        )
    if mime_type in XLSX_MIME_TYPES or suffix == ".xlsx":
        if shutil.which(SOFFICE_COMMAND):
            cache_was_valid = _is_preview_cache_valid(task_file, checksum)
            page_images = _render_office_preview(task_file, checksum)
            pdf_path = _convert_office_to_pdf(task_file)
            return FilePreviewResponse(
                id=task_file.id,
                filename=task_file.filename,
                mime_type=mime_type,
                size=task_file.size,
                mode="gallery",
                content=_extract_office_text(task_file, data, pdf_path),
                page_count=len(page_images),
                page_image_urls=[f"/api/files/{task_file.id}/preview/pages/{image.name}?v={checksum}" for image in page_images],
                download_url=f"/api/files/{task_file.id}/content",
                message=_preview_cache_message(cache_was_valid),
            )
        content = _extract_openxml_text(data, "xlsx")
        return FilePreviewResponse(
            id=task_file.id,
            filename=task_file.filename,
            mime_type=mime_type,
            size=task_file.size,
            mode="text",
            content=content or "无法提取该表格文件的文本预览。",
            download_url=f"/api/files/{task_file.id}/content",
            message="当前环境未安装 LibreOffice，已回退为文本预览。",
        )
    if suffix in LEGACY_OFFICE_EXTENSIONS:
        if shutil.which(SOFFICE_COMMAND):
            cache_was_valid = _is_preview_cache_valid(task_file, checksum)
            page_images = _render_office_preview(task_file, checksum)
            pdf_path = _convert_office_to_pdf(task_file)
            return FilePreviewResponse(
                id=task_file.id,
                filename=task_file.filename,
                mime_type=mime_type,
                size=task_file.size,
                mode="gallery",
                content=_extract_office_text(task_file, data, pdf_path),
                page_count=len(page_images),
                page_image_urls=[f"/api/files/{task_file.id}/preview/pages/{image.name}?v={checksum}" for image in page_images],
                download_url=f"/api/files/{task_file.id}/content",
                message=_preview_cache_message(cache_was_valid),
            )
        return FilePreviewResponse(
            id=task_file.id,
            filename=task_file.filename,
            mime_type=mime_type,
            size=task_file.size,
            mode="download",
            download_url=f"/api/files/{task_file.id}/content",
            message="当前环境未安装 LibreOffice，暂时无法生成该 Office 文件的版式预览。",
        )
    return FilePreviewResponse(
        id=task_file.id,
        filename=task_file.filename,
        mime_type=mime_type,
        size=task_file.size,
        mode="download",
        download_url=f"/api/files/{task_file.id}/content",
    )


def _preview_dir(task_file: TaskFile) -> Path:
    path = Path(PREVIEW_CACHE_DIR) / f"file-{task_file.id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _preview_dir_path(task_file: TaskFile) -> Path:
    return Path(PREVIEW_CACHE_DIR) / f"file-{task_file.id}"


def _preview_hash_path(task_file: TaskFile) -> Path:
    return _preview_dir_path(task_file) / ".source.sha256"


def _is_preview_cache_valid(task_file: TaskFile, checksum: str) -> bool:
    hash_path = _preview_hash_path(task_file)
    return hash_path.exists() and hash_path.read_text(encoding="utf-8", errors="replace").strip() == checksum


def _prepare_preview_cache(task_file: TaskFile, checksum: str) -> None:
    preview_dir = _preview_dir_path(task_file)
    if not _is_preview_cache_valid(task_file, checksum):
        if preview_dir.exists():
            shutil.rmtree(preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)


def _mark_preview_cache_current(task_file: TaskFile, checksum: str) -> None:
    _preview_hash_path(task_file).write_text(checksum, encoding="utf-8")


def _preview_cache_message(cache_was_valid: bool) -> str:
    if cache_was_valid:
        return "云端哈希校验通过，直接读取已解析的图片缓存。"
    return "文件是新文件或哈希已变化，已在云端重新解析并生成图片缓存。"


def _ensure_source_copy(task_file: TaskFile) -> Path:
    preview_dir = _preview_dir(task_file)
    ext = Path(task_file.filename).suffix
    source_path = preview_dir / f"source{ext}"
    if not source_path.exists():
        source_path.write_bytes(storage.read(task_file.storage_key))
    return source_path


def _render_pdf_pages(pdf_path: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if not any(output_dir.glob("page-*.png")):
        command = [
            "pdftoppm",
            "-png",
            "-r",
            str(PDF_PREVIEW_DPI),
            str(pdf_path),
            str(output_dir / "page"),
        ]
        subprocess.run(command, check=True, capture_output=True)
    return sorted(output_dir.glob("page-*.png"), key=_preview_page_sort_key)


def _preview_page_sort_key(path: Path) -> int:
    stem = path.stem
    number = stem.rsplit("-", 1)[-1]
    return int(number) if number.isdigit() else 0


def _render_pdf_preview(task_file: TaskFile, checksum: str) -> list[Path]:
    _prepare_preview_cache(task_file, checksum)
    preview_dir = _preview_dir(task_file)
    source_path = _ensure_source_copy(task_file)
    pages_dir = preview_dir / "pdf-pages"
    pages = _render_pdf_pages(source_path, pages_dir)
    _mark_preview_cache_current(task_file, checksum)
    return pages


def _convert_office_to_pdf(task_file: TaskFile) -> Path:
    preview_dir = _preview_dir(task_file)
    pdf_path = preview_dir / "office-preview.pdf"
    if pdf_path.exists():
        return pdf_path

    source_path = _ensure_source_copy(task_file)
    with tempfile.TemporaryDirectory(prefix="wensai-office-") as tmpdir:
        working_dir = Path(tmpdir)
        input_path = working_dir / Path(task_file.filename).name
        input_path.write_bytes(source_path.read_bytes())
        command = [
            SOFFICE_COMMAND,
            "--headless",
            "--nologo",
            "--nodefault",
            "--nolockcheck",
            "--nofirststartwizard",
            "--convert-to",
            "pdf",
            "--outdir",
            str(working_dir),
            str(input_path),
        ]
        subprocess.run(command, check=True, capture_output=True)
        generated_pdf = working_dir / f"{input_path.stem}.pdf"
        if not generated_pdf.exists():
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Office preview conversion failed")
        shutil.copyfile(generated_pdf, pdf_path)

    return pdf_path


def _render_office_preview(task_file: TaskFile, checksum: str) -> list[Path]:
    _prepare_preview_cache(task_file, checksum)
    preview_dir = _preview_dir(task_file)
    pdf_path = _convert_office_to_pdf(task_file)
    pages_dir = preview_dir / "office-pages"
    pages = _render_pdf_pages(pdf_path, pages_dir)
    _mark_preview_cache_current(task_file, checksum)
    return pages


@router.post("/tasks/{task_id}/files", response_model=TaskFileResponse, status_code=status.HTTP_201_CREATED)
async def upload_task_file(
    task_id: int,
    file: UploadFile = File(...),
    relative_path: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _get_accessible_task(db, task_id, current_user.id)
    filename = _safe_relative_path(relative_path, file.filename or "upload.bin")
    data = await file.read()
    key = storage.save(data, filename)
    task_file = TaskFile(
        task_id=task_id,
        user_id=current_user.id,
        workspace_id=task.workspace_id,
        filename=filename,
        storage_key=key,
        mime_type=file.content_type,
        size=len(data),
        source="upload",
    )
    db.add(task_file)
    db.commit()
    db.refresh(task_file)

    if DISPATCH_AGENT_TASKS:
        transfer = await transfer_file_to_agentsdk(
            task_id,
            task_file.filename,
            data,
            task_file.content_type,
            filename,
            task.workspace.root_path if task.workspace else None,
        )
        if transfer:
            await create_task_event(
                db,
                task_id,
                "file_saved",
                message=task_file.filename,
                payload={"file_id": task_file.id, "sandbox_path": transfer.get("path"), "relative_path": filename},
            )
        else:
            await create_task_event(
                db,
                task_id,
                "tool_call_failed",
                level="warning",
                message=task_file.filename,
                payload={"file_id": task_file.id},
            )
    return task_file


@router.post("/tasks/{task_id}/files/create", response_model=TaskFileResponse, status_code=status.HTTP_201_CREATED)
async def create_task_file(
    task_id: int,
    payload: TaskFileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task = _get_accessible_task(db, task_id, current_user.id)
    kind = payload.kind.strip().lower()
    if kind not in {"file", "folder"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file kind")

    if kind == "folder":
        filename = _folder_marker_path(payload.filename)
        data = b""
        mime_type = "application/x-wensai-folder"
        source = "folder"
    else:
        filename = _safe_relative_path(payload.filename, "untitled.md")
        data = payload.content.encode("utf-8")
        mime_type = mimetypes.guess_type(filename)[0] or "text/plain"
        source = "manual"

    _ensure_unique_task_filename(db, task_id, filename)
    key = storage.save(data, filename)
    task_file = TaskFile(
        task_id=task_id,
        user_id=current_user.id,
        workspace_id=task.workspace_id,
        filename=filename,
        storage_key=key,
        mime_type=mime_type,
        size=len(data),
        source=source,
    )
    db.add(task_file)
    db.commit()
    db.refresh(task_file)

    if DISPATCH_AGENT_TASKS and kind == "file":
        transfer = await transfer_file_to_agentsdk(
            task_id,
            task_file.filename,
            data,
            task_file.content_type,
            filename,
            task.workspace.root_path if task.workspace else None,
        )
        if transfer:
            await create_task_event(
                db,
                task_id,
                "file_saved",
                message=task_file.filename,
                payload={"file_id": task_file.id, "sandbox_path": transfer.get("path"), "relative_path": filename},
            )
        else:
            await create_task_event(
                db,
                task_id,
                "tool_call_failed",
                level="warning",
                message=task_file.filename,
                payload={"file_id": task_file.id},
            )
    return task_file


@router.get("/tasks/{task_id}/files", response_model=list[TaskFileResponse])
def list_task_files(task_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_accessible_task(db, task_id, current_user.id)
    files = db.query(TaskFile).filter(TaskFile.task_id == task_id).order_by(TaskFile.created_at.asc()).all()
    return [_task_file_response(file) for file in files]


@router.get("/workspaces/{workspace_id}/files", response_model=list[WorkspaceFileResponse])
def list_workspace_files(workspace_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    _get_accessible_workspace(db, workspace_id, current_user.id)
    files = (
        db.query(TaskFile)
        .filter(TaskFile.workspace_id == workspace_id)
        .order_by(TaskFile.filename.asc(), TaskFile.created_at.asc(), TaskFile.id.asc())
        .all()
    )
    return [_workspace_file_response(file) for file in files]


@router.get("/files/{file_id}/preview", response_model=FilePreviewResponse)
def preview_task_file(
    file_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    task_file = _get_accessible_file(db, file_id, current_user.id)
    return _build_preview(task_file)


@router.get("/files/{file_id}/preview/pages/{page_name}")
def preview_task_file_page(file_id: int, page_name: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task_file = _get_accessible_file(db, file_id, current_user.id)
    if "/" in page_name or ".." in page_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid preview page")

    preview_dir = _preview_dir(task_file)
    pages_dir = preview_dir / ("pdf-pages" if Path(task_file.filename).suffix.lower() == ".pdf" else "office-pages")
    page_path = (pages_dir / page_name).resolve()
    if not str(page_path).startswith(str(pages_dir.resolve())) or not page_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Preview page not found")
    return FileResponse(page_path, media_type="image/png")


@router.get("/files/{file_id}/content")
def read_task_file_inline(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task_file = _get_accessible_file(db, file_id, current_user.id)
    return Response(content=storage.read(task_file.storage_key), media_type=task_file.mime_type or "application/octet-stream")


@router.get("/files/{file_id}")
def download_task_file(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task_file = _get_accessible_file(db, file_id, current_user.id)
    return Response(
        content=storage.read(task_file.storage_key),
        media_type=task_file.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{task_file.filename}"'},
    )


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task_file(file_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    task_file = _get_accessible_file(db, file_id, current_user.id)
    task = task_file.task
    if DISPATCH_AGENT_TASKS and task:
        deleted = await delete_file_from_agentsdk_sandbox(
            task_file.task_id,
            task_file.filename,
            "output" if task_file.source == "agent_output" else "input",
            task.workspace.root_path if task.workspace else None,
        )
        if not deleted:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="删除沙盒内真实文件失败")
    storage.delete(task_file.storage_key)
    preview_dir = _preview_dir_path(task_file)
    if preview_dir.exists():
        shutil.rmtree(preview_dir)
    db.delete(task_file)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
