from celery import Celery

from app.config import REDIS_URL, TIMEZONE


celery_app = Celery("wensai", broker=REDIS_URL, backend=REDIS_URL)
celery_app.conf.update(
    task_track_started=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=TIMEZONE,
    enable_utc=False,
)

celery_app.autodiscover_tasks(["app.tasks"])
