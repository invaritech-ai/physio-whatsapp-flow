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
        
        # 3. Session End Notifications (When session completes based on duration)
        # Find started appointments that have ended (within last 5 mins)
        statement_ended = select(Appointment).where(
            Appointment.end_time <= now,
            Appointment.end_time >= five_mins_ago,
            Appointment.status == "started"
        )
        ended_appointments = session.exec(statement_ended).all()
        
        # Debug: Check for any started appointments to see why they're not being picked up
        all_started = session.exec(select(Appointment).where(Appointment.status == "started")).all()
        if all_started:
            for a in all_started:
                print(f"Started Appt {a.id}: end_time={a.end_time}, now={now}, ended={a.end_time <= now}")
        
        for appt in ended_appointments:
            if physio_number:
                # Find the physio user to set their conversation state
                statement_physio_user = select(User).where(User.phone_number == physio_number)
                physio_user = session.exec(statement_physio_user).first()
                
                if physio_user:
                    # Set physio in payment flow state
                    physio_user.conversation_state = "awaiting_payment_status"
                    physio_user.active_appointment_id = appt.id
                    session.add(physio_user)
                    
                    msg = f"Session {appt.id} completed ({appt.duration_minutes} min).\n\nHow was payment handled? Reply with:\n1️⃣ Payment received\n2️⃣ FPS\n3️⃣ Consolidating with other session"
                    try:
                        send_whatsapp_message(physio_number, msg)
                        print(f"[AUTO-END] Triggered payment flow for Appointment {appt.id}")
                    except Exception as e:
                        print(f"Failed to send session end notification: {e}")

        session.commit()
    print(f"Scheduler run at {now}: Sent {len(upcoming_appointments)} customer reminders, {len(starting_appointments)} physio notifications, {len(ended_appointments)} session end prompts.")

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
