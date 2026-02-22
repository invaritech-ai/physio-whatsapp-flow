"""Therapist routes package - aggregates all therapist endpoints."""

from fastapi import APIRouter

from app.api.v1.routes.therapist import calendly_feed, invoices, notifications, onboarding, patients, sessions

router = APIRouter()

# Register therapist routes
router.include_router(onboarding.router)
router.include_router(sessions.router)
router.include_router(patients.router)
router.include_router(invoices.router)
router.include_router(notifications.router)
router.include_router(calendly_feed.router)
# Compatibility mount for frontend contract:
# /api/v1/therapist/sessions/*
router.include_router(sessions.router, prefix="/therapist")

__all__ = ["router"]
