"""Admin routes package - aggregates all admin endpoints."""

from fastapi import APIRouter

from app.api.v1.routes.admin import specialties

router = APIRouter()

# Register specialty routes
router.include_router(specialties.router)

__all__ = ["router"]
