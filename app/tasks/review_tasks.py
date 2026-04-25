import json
import logging

from app.celery_app import celery_app
from app.database import SessionLocal
from app.models.paper import Paper
from app.models.review import Review
from app.services.agent import review_paper
from app.storage import storage

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.review_tasks.run_ai_review_task")
def run_ai_review_task(paper_id: int, review_id: int) -> None:
    db = SessionLocal()
    try:
        paper = db.query(Paper).filter(Paper.id == paper_id).first()
        review = db.query(Review).filter(Review.id == review_id).first()
        if not paper or not review:
            logger.error("AI review task missing paper or review: paper_id=%s review_id=%s", paper_id, review_id)
            return

        review.status = "running"
        db.commit()

        file_path = storage.local_path(paper.file_path) if paper.file_path else None
        result = review_paper(
            title=paper.title,
            requirements=paper.abstract,
            file_path=file_path,
        )

        review.score = result.get("score")
        review.content = result.get("content")
        review.recommendation = result.get("recommendation")
        review.llm_log = result.get("llm_log")
        review.status = "completed"
        db.commit()
    except Exception as exc:
        logger.exception("AI review task failed: paper_id=%s review_id=%s", paper_id, review_id)
        review = db.query(Review).filter(Review.id == review_id).first()
        if review:
            review.status = "failed"
            review.content = f"AI review failed: {exc}"
            review.llm_log = json.dumps({"error": str(exc)}, ensure_ascii=False)
            db.commit()
    finally:
        db.close()
