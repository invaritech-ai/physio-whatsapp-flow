from app.worker import celery_app


@celery_app.task(name="tasks.ping")
def ping() -> str:
    return "pong"
