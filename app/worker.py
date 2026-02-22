from celery import Celery
from kombu import Queue

from app.core.config import settings

celery_app = Celery("physio_whatsapp")

celery_app.conf.update(
    broker_url=settings.celery_broker_url,
    result_backend=settings.celery_result_backend,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_default_queue="default",
    task_queues=(
        Queue("default"),
        Queue("documents"),
        Queue("integrations"),
        Queue("notifications"),
    ),
    task_routes={
        "tasks.process_whatsapp_message": {"queue": "default"},
        "tasks.generate_invoice_pdf": {"queue": "documents"},
        "tasks.process_calendly_webhook_event": {"queue": "integrations"},
        "tasks.sync_therapist_event_types": {"queue": "integrations"},
        "tasks.send_booking_link_followup": {"queue": "notifications"},
    },
    beat_schedule={
        "sync-therapist-event-types": {
            "task": "tasks.sync_therapist_event_types",
            "schedule": settings.celery_sync_interval_seconds,
            "options": {"queue": "integrations"},
        },
    },
)

# Import tasks to register them
from app.tasks import process_whatsapp  # noqa: E402, F401
from app.tasks import booking_followups, calendly, invoice_documents, sync  # noqa: E402, F401
