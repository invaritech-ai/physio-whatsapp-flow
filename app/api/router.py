from fastapi import APIRouter

from app.api.root import router as root_router
from app.api.v1.routes import whatsapp as whatsapp_router
from app.api.v1 import api_router as v1_router

api_router = APIRouter()
api_router.include_router(root_router)
# Backward-compatibility alias for Twilio webhooks configured at /whatsapp.
# Hidden from OpenAPI so canonical contract remains /api/v1/whatsapp.
api_router.include_router(whatsapp_router.router, include_in_schema=False)
api_router.include_router(v1_router)
