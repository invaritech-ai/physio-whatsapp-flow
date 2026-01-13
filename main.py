from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from datetime import datetime, timedelta
from sqlmodel import SQLModel, Session, create_engine, select
from contextlib import asynccontextmanager
from bot_logic import process_message
from models import User, Appointment
from services.twilio_client import send_whatsapp_message
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import os
import uvicorn

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./physio.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session

# Scheduler for reminders
scheduler = AsyncIOScheduler()

def send_scheduled_reminders():
    # Logic to check DB for upcoming appointments
    with Session(engine) as session:
        now = datetime.utcnow()
        thirty_mins_later = now + timedelta(minutes=30)
        
        # 1. Customer Reminders (30 mins before)
        # Find appointments starting between now and 30 mins from now, where reminder not sent
        statement = select(Appointment).where(
            Appointment.start_time > now,
            Appointment.start_time <= thirty_mins_later,
            Appointment.reminder_sent == False
        )
        upcoming_appointments = session.exec(statement).all()
        
        for appt in upcoming_appointments:
            # Fetch user
            user = session.get(User, appt.customer_id)
            if user:
                msg = f"Reminder: You have a physio appointment starting at {appt.start_time} (in approx 30 mins)."
                try:
                    send_whatsapp_message(user.phone_number, msg)
                    appt.reminder_sent = True
                    session.add(appt)
                except Exception as e:
                    print(f"Failed to send reminder to {user.phone_number}: {e}")
        
        # 2. Physio Notifications (At start time)
        # Find appointments that have started (or starting now) where physio not notified
        # We give a small buffer (e.g. within last 5 mins to catch up)
        five_mins_ago = now - timedelta(minutes=5)
        statement_physio = select(Appointment).where(
            Appointment.start_time <= now,
            Appointment.start_time >= five_mins_ago,
            Appointment.physio_notified == False
        )
        starting_appointments = session.exec(statement_physio).all()
        
        physio_number = os.getenv("PHYSIO_PHONE_NUMBER")
        
        for appt in starting_appointments:
            if physio_number:
                msg = f"Appointment Starting ID: {appt.id}\nCustomer ID: {appt.customer_id}\nPlease reply 'start {appt.id}' or 'cancel {appt.id}'."
                try:
                    send_whatsapp_message(physio_number, msg)
                    appt.physio_notified = True
                    session.add(appt)
                except Exception as e:
                    print(f"Failed to send physio notification: {e}")

        session.commit()
    print(f"Scheduler run at {now}: Sent {len(upcoming_appointments)} customer reminders and {len(starting_appointments)} physio notifications.")

@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    scheduler.add_job(send_scheduled_reminders, 'interval', minutes=5)
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

@app.post("/whatsapp")
async def whatsapp_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        form_data = await request.form()
        
        # We use a new session for the background processing or dependency injection
        # Note: In async, Session needs care. 
        # Using a fresh session here for the logic.
        with Session(engine) as session:
             await process_message(dict(form_data), session)
        
        return {"status": "success"}
    except Exception as e:
        import traceback
        error_msg = f"Error: {str(e)}\n{traceback.format_exc()}"
        print(error_msg)
        return JSONResponse(status_code=500, content={"message": str(e), "traceback": traceback.format_exc()})

@app.get("/")
def read_root():
    return {"message": "Physio Bot API is running"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
