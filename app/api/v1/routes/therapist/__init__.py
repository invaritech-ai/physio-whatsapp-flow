"""Therapist routes package - aggregates all therapist endpoints."""

from fastapi import APIRouter

from app.api.v1.routes.therapist import onboarding, sessions

router = APIRouter()

# Register therapist routes
router.include_router(onboarding.router)
router.include_router(sessions.router)

__all__ = ["router"]
