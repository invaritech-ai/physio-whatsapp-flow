"""Therapist routes package - aggregates all therapist endpoints."""

from fastapi import APIRouter

from app.api.v1.routes.therapist import onboarding

router = APIRouter()

# Register therapist routes
router.include_router(onboarding.router)

__all__ = ["router"]
