import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session, joinedload

from app.database import SessionLocal
from app.dependencies import get_db, get_current_user
from app.limiter import limiter
from app.storage import storage
from app.models.paper import Paper
from app.models.review import Review
from app.models.user import User
from app.schemas.review import ReviewCreate, ReviewUpdate, ReviewResponse
from app.services.agent import review_paper

logger = logging.getLogger(__name__)

router = APIRouter(tags=["reviews"])


@router.get("/api/papers/{paper_id}/reviews", response_model=list[ReviewResponse])
def list_reviews(
    paper_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    reviews = (
        db.query(Review)
        .options(joinedload(Review.reviewer))
        .filter(Review.paper_id == paper_id)
        .order_by(Review.created_at.desc())
        .all()
    )
    return reviews


@router.post("/api/papers/{paper_id}/reviews", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
def create_review(
    paper_id: int,
    review_in: ReviewCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a manual (human) review."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    # Check if user already reviewed this paper
    existing = db.query(Review).filter(
        Review.paper_id == paper_id,
        Review.reviewer_id == current_user.id,
        Review.source == "manual",
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You have already reviewed this paper",
        )

    review = Review(
        paper_id=paper_id,
        reviewer_id=current_user.id,
        source="manual",
        score=review_in.score,
        content=review_in.content,
        recommendation=review_in.recommendation,
    )
    db.add(review)

    if paper.status == "pending":
        paper.status = "under_review"

    db.commit()
    db.refresh(review)
    return review


def _run_ai_review(review_id: int, paper_title: str, paper_abstract: str | None, file_path: str | None):
    """Background task: call LLM and update the review record."""
    db = SessionLocal()
    try:
        result = review_paper(title=paper_title, requirements=paper_abstract, file_path=file_path)
        review = db.query(Review).filter(Review.id == review_id).first()
        if not review:
            return
        review.score = result["score"]
        review.content = result["content"]
        review.recommendation = result["recommendation"]
        review.llm_log = result.get("llm_log")
        review.status = "completed"
        db.commit()
    except Exception as e:
        logger.exception("AI review background task failed for review %s", review_id)
        review = db.query(Review).filter(Review.id == review_id).first()
        if review:
            review.status = "failed"
            review.content = f"AI review failed: {str(e)}"
            db.commit()
    finally:
        db.close()


@router.post("/api/papers/{paper_id}/ai-review", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
def create_ai_review(
    request: Request,
    paper_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger AI review for a paper. Returns immediately with a pending review."""
    paper = db.query(Paper).filter(Paper.id == paper_id).first()
    if not paper:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Paper not found")

    # Check if AI already reviewed this paper
    existing = db.query(Review).filter(
        Review.paper_id == paper_id,
        Review.source == "ai",
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="AI has already reviewed this paper",
        )

    # Create a pending review record
    review = Review(
        paper_id=paper_id,
        reviewer_id=None,
        source="ai",
        status="pending",
        score=0,
        content="",
        recommendation="minor_revision",
    )
    db.add(review)

    if paper.status == "pending":
        paper.status = "under_review"

    db.commit()
    db.refresh(review)

    # Schedule the actual LLM call in the background
    pdf_path = None
    if paper.file_path:
        pdf_path = storage.local_path(paper.file_path)

    background_tasks.add_task(
        _run_ai_review,
        review_id=review.id,
        paper_title=paper.title,
        paper_abstract=paper.abstract,
        file_path=pdf_path,
    )

    return review


@router.put("/api/reviews/{review_id}", response_model=ReviewResponse)
def update_review(
    review_id: int,
    review_in: ReviewUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    if review.source == "ai":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot edit AI reviews")
    if review.reviewer_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    update_data = review_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(review, key, value)

    db.commit()
    db.refresh(review)
    return review


@router.delete("/api/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    review = db.query(Review).filter(Review.id == review_id).first()
    if not review:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Review not found")
    if review.source == "ai" and review.reviewer_id is None:
        # Anyone can delete AI reviews
        pass
    elif review.reviewer_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    db.delete(review)
    db.commit()
