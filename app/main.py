from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timedelta
import os

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session, select

from app.bot_logic import process_message
from app.core.config import settings
from app.db.session import create_db_and_tables, engine
from app.models import Appointment, User
from app.services.twilio_client import send_whatsapp_message


scheduler = AsyncIOScheduler()


def send_scheduled_reminders() -> None:
    with Session(engine) as session:
        now = datetime.utcnow()
        thirty_mins_later = now + timedelta(minutes=30)

        statement = select(Appointment).where(
            Appointment.start_time > now,
            Appointment.start_time <= thirty_mins_later,
            Appointment.reminder_sent == False,  # noqa: E712
        )
        upcoming_appointments = session.exec(statement).all()

        for appt in upcoming_appointments:
            user = session.get(User, appt.customer_id)
            if not user:
                continue
            msg = f"Reminder: You have a physio appointment starting at {appt.start_time} (in approx 30 mins)."
            try:
                send_whatsapp_message(user.phone_number, msg)
                appt.reminder_sent = True
                session.add(appt)
            except Exception as e:
                print(f"Failed to send reminder to {user.phone_number}: {e}")

        five_mins_ago = now - timedelta(minutes=5)
        statement_physio = select(Appointment).where(
            Appointment.start_time <= now,
            Appointment.start_time >= five_mins_ago,
            Appointment.physio_notified == False,  # noqa: E712
        )
        starting_appointments = session.exec(statement_physio).all()

        physio_number = settings.physio_phone_number or os.getenv("PHYSIO_PHONE_NUMBER")
        for appt in starting_appointments:
            if not physio_number:
                continue
            msg = (
                f"Appointment Starting ID: {appt.id}\nCustomer ID: {appt.customer_id}\n"
                f"Please reply 'start {appt.id}' or 'cancel {appt.id}'."
            )
            try:
                send_whatsapp_message(physio_number, msg)
                appt.physio_notified = True
                session.add(appt)
            except Exception as e:
                print(f"Failed to send physio notification: {e}")

        statement_ended = select(Appointment).where(
            Appointment.end_time <= now,
            Appointment.end_time >= five_mins_ago,
            Appointment.status == "started",
        )
        ended_appointments = session.exec(statement_ended).all()

        all_started = session.exec(select(Appointment).where(Appointment.status == "started")).all()
        for a in all_started:
            print(f"Started Appt {a.id}: end_time={a.end_time}, now={now}, ended={a.end_time <= now}")

        for appt in ended_appointments:
            if not physio_number:
                continue

            statement_physio_user = select(User).where(User.phone_number == physio_number)
            physio_user = session.exec(statement_physio_user).first()
            if not physio_user:
                continue

            physio_user.conversation_state = "awaiting_payment_status"
            physio_user.active_appointment_id = appt.id
            session.add(physio_user)

            msg = (
                f"Session {appt.id} completed ({appt.duration_minutes} min).\n\nHow was payment handled? Reply with:\n"
                "1️⃣ Payment received\n2️⃣ FPS\n3️⃣ Consolidating with other session"
            )
            try:
                send_whatsapp_message(physio_number, msg)
                print(f"[AUTO-END] Triggered payment flow for Appointment {appt.id}")
            except Exception as e:
                print(f"Failed to send session end notification: {e}")

        session.commit()

    print(
        f"Scheduler run at {now}: Sent {len(upcoming_appointments)} customer reminders, "
        f"{len(starting_appointments)} physio notifications, {len(ended_appointments)} session end prompts."
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_db_and_tables()
    scheduler.add_job(send_scheduled_reminders, "interval", minutes=5)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


@app.post("/whatsapp")
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


@app.get("/")
def read_root():
    return {"message": "Physio Bot API is running"}
