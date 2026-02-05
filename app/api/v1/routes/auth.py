from fastapi import APIRouter, Depends

from app.core.auth import get_current_user

router = APIRouter()


@router.get("/me")
def read_me(current_user: dict = Depends(get_current_user)):
    return current_user
