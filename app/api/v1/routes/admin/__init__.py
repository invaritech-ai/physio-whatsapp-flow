"""Admin routes package - aggregates all admin endpoints."""

from fastapi import APIRouter

from app.api.v1.routes.admin import (
    access_requests,
    auth_events,
    clients,
    invoices,
    payments,
    plans,
    specialties,
    therapists,
    users,
)

router = APIRouter()

# Register admin routes
router.include_router(access_requests.router)
router.include_router(auth_events.router)
router.include_router(clients.router)
router.include_router(invoices.router)
router.include_router(plans.router)
router.include_router(payments.router)
router.include_router(specialties.router)
router.include_router(therapists.router)
router.include_router(users.router)

__all__ = ["router"]
