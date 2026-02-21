from fastapi import APIRouter

from app.api.v1.routes import auth, health, webhooks, whatsapp
from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.therapist import router as therapist_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(whatsapp.router)
api_router.include_router(webhooks.router)
api_router.include_router(admin_router)
api_router.include_router(therapist_router)

__all__ = ["api_router"]
