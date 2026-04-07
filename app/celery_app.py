from celery import Celery

from app.config import settings

celery_app = Celery(
    "leadenrich",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.enrichment.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)
