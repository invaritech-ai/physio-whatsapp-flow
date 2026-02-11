"""Admin routes package - aggregates all admin endpoints."""

from fastapi import APIRouter

from app.api.v1.routes.admin import auth_events, access_requests, specialties, therapists, users

router = APIRouter()

# Register admin routes
router.include_router(access_requests.router)
router.include_router(auth_events.router)
router.include_router(specialties.router)
router.include_router(therapists.router)
router.include_router(users.router)

__all__ = ["router"]
