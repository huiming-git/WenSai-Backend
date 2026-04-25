import os
import tempfile
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, status
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session, joinedload

from app.config import MAX_UPLOAD_SIZE_MB
from app.constants import ALLOWED_UPLOAD_EXTENSIONS, UPLOAD_CHUNK_SIZE
from app.dependencies import get_db, get_current_user
from app.models.paper import Paper
from app.models.user import User
from app.schemas.paper import PaperCreate, PaperUpdate, PaperFinalize, PaperResponse, PaperListResponse
from app.storage import storage

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.get("", response_model=PaperListResponse)
def list_papers(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    status_filter: str | None = Query(None, alias="status"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Paper).options(joinedload(Paper.author))

    if status_filter:
        query = query.filter(Paper.status == status_filter)

    total = query.count()
    items = query.order_by(Paper.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    return PaperListResponse(items=items, total=total, page=page, page_size=page_size)


@router.post("", response_model=PaperResponse, status_code=status.HTTP_201_CREATED)
def create_paper(
    paper_in: PaperCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    paper = Paper(
        title=paper_in.title,
        abstract=paper_in.abstract,
        author_id=current_user.id,
    )
    db.add(paper)
    db.commit()
    db.refresh(paper)
    return paper


@router.get("/{paper_id}", response_model=PaperResponse)
def get_paper(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    paper = db.query(Paper).options(joinedload(Paper.author)).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")
    return paper


@router.put("/{paper_id}", response_model=PaperResponse)
def update_paper(
    paper_id: int,
    paper_in: PaperUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")
    if paper.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    update_data = paper_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(paper, key, value)

    db.commit()
    db.refresh(paper)
    return paper


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_paper(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")
    if paper.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    db.delete(paper)
    db.commit()


VALID_DECISIONS = {"accepted", "rejected", "revision"}
FINAL_STATUSES = {"accepted", "rejected"}


@router.post("/{paper_id}/finalize", response_model=PaperResponse)
def finalize_paper(
    paper_id: int,
    body: PaperFinalize,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit final decision for a paper. Moves it into the completed pool."""
    paper = db.query(Paper).options(joinedload(Paper.author)).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    if paper.status in FINAL_STATUSES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Paper already finalized")

    if body.decision not in VALID_DECISIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid decision. Must be one of: {', '.join(VALID_DECISIONS)}",
        )

    paper.status = body.decision
    paper.final_score = body.score
    paper.final_comment = body.comment
    db.commit()
    db.refresh(paper)
    return paper


@router.post("/{paper_id}/upload", response_model=PaperResponse)
async def upload_file(
    paper_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")
    if paper.author_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if not file.filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No file provided")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}",
        )

    max_size_bytes = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    current_size = 0
    temp_path = None

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name

        async with aiofiles.open(temp_path, "wb") as out_file:
            while True:
                chunk = await file.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                current_size += len(chunk)
                if current_size > max_size_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail=f"File too large. Max allowed size is {MAX_UPLOAD_SIZE_MB}MB",
                    )
                await out_file.write(chunk)

        key = storage.save_file(temp_path, file.filename)
        temp_path = None

        if not storage.exists(key):
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="File save failed")

        paper.file_path = key
        db.commit()
        db.refresh(paper)
        return paper
    finally:
        await file.close()
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


@router.get("/{paper_id}/file")
def download_file(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")
    if not paper.file_path:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No file uploaded")

    if not storage.exists(paper.file_path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found in storage")

    # If local storage, serve directly; otherwise stream bytes
    local = storage.local_path(paper.file_path)
    ext = os.path.splitext(paper.file_path)[1] or ""
    if local:
        return FileResponse(local, filename=f"{paper.title}{ext}")

    data = storage.read(paper.file_path)
    return Response(
        content=data,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{paper.title}{ext}"'},
    )
