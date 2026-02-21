from fastapi import APIRouter


router = APIRouter(tags=["System"])


@router.get("/health")
def read_health() -> dict[str, str]:
    """Simple API heartbeat endpoint for monitoring and smoke tests."""
    return {"status": "ok"}
