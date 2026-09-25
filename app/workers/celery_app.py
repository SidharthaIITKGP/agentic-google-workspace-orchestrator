from celery import Celery

from app.core.config import get_settings


settings = get_settings()
celery_app = Celery(
    "workspace_orchestrator",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    beat_schedule={
        "enqueue-connected-users-every-15-minutes": {
            "task": "workspace.enqueue_connected_users",
            "schedule": 900.0,
            "options": {"expires": 840.0},
        }
    },
)
