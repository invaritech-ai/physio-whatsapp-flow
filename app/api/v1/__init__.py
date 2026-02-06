from fastapi import APIRouter

from app.api.v1.routes import auth, session_notes, whatsapp

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(whatsapp.router)
api_router.include_router(session_notes.router)

__all__ = ["api_router"]
