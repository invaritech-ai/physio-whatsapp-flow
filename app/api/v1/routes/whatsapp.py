from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from app.bot_logic import process_message
from app.db.session import engine

router = APIRouter()


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        form_data = await request.form()
        with Session(engine) as session:
            await process_message(dict(form_data), session)
        return {"status": "success"}
    except Exception as e:
        import traceback

        print(f"Error: {str(e)}\n{traceback.format_exc()}")
        return JSONResponse(status_code=500, content={"message": str(e), "traceback": traceback.format_exc()})
