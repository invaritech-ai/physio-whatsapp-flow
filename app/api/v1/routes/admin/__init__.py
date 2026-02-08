"""Admin routes package - aggregates all admin endpoints."""

from fastapi import APIRouter

from app.api.v1.routes.admin import specialties, therapists

router = APIRouter()

# Register admin routes
router.include_router(specialties.router)
router.include_router(therapists.router)

__all__ = ["router"]
