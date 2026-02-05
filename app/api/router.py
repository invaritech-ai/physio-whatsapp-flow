from fastapi import APIRouter

from app.api.root import router as root_router
from app.api.v1 import api_router as v1_router

api_router = APIRouter()
api_router.include_router(root_router)
api_router.include_router(v1_router)
