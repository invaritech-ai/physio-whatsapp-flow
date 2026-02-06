from __future__ import annotations

import os

from sqlmodel import Session, select

from app.core.config import settings
from app.models import Appointment, Payment, SessionNote, User
from app.services.calendly import check_availability
from app.services.twilio_client import send_whatsapp_message

ADMIN_PHONE = settings.admin_phone_number or os.getenv("ADMIN_PHONE_NUMBER")
PHYSIO_PHONE = settings.physio_phone_number or os.getenv("PHYSIO_PHONE_NUMBER")

DEBUG_MODE = settings.debug_mode


def debug_log(message: str) -> None:
    if DEBUG_MODE:
        print(message)


def get_or_create_user(session: Session, phone: str, name: str | None = None):
    statement = select(User).where(User.phone_number == phone)
    user = session.exec(statement).first()

    expected_role = "customer"
    if phone == ADMIN_PHONE:
        expected_role = "admin"
    elif phone == PHYSIO_PHONE:
        expected_role = "physio"

    if not user:
        print(f"DEBUG: Creating new user {phone} as {expected_role}")
        user = User(phone_number=phone, name=name, role=expected_role)
        session.add(user)
        session.commit()
        session.refresh(user)
    else:
        if not DEBUG_MODE and user.role != expected_role:
            print(f"DEBUG: Correcting role for {phone} from {user.role} to {expected_role}")
            user.role = expected_role
            session.add(user)
            session.commit()
            session.refresh(user)

    return user


async def process_message(form_data: dict, db: Session):
    sender = form_data.get("From")
    body_normalized = form_data.get("Body", "").strip().lower()
    num_media = int(form_data.get("NumMedia", 0))
    media_url = form_data.get("MediaUrl0")

    user = get_or_create_user(db, sender)
    debug_log(f"📱 [{user.role.upper()}] {sender}: {body_normalized}")

    if DEBUG_MODE and ("switch to" in body_normalized or "be " in body_normalized):
        if "customer" in body_normalized:
            user.role = "customer"
            db.add(user)
            db.commit()
            send_whatsapp_message(sender, "✅ Switched to CUSTOMER role.\n\nYou can now book appointments. Say 'Hi' to start!")
            return
        if "admin" in body_normalized:
            user.role = "admin"
            db.add(user)
            db.commit()
            send_whatsapp_message(sender, "✅ Switched to ADMIN role.\n\nYou can now approve payments with 'approve <payment_id>'")
            return
        if "physio" in body_normalized:
            user.role = "physio"
            db.add(user)
            db.commit()
            send_whatsapp_message(sender, "✅ Switched to PHYSIO role.\n\nYou can start sessions with 'start <appointment_id>'")
            return

    if user.role == "customer":
        await handle_customer_message(user, body_normalized, num_media, media_url, sender, db)
    elif user.role == "physio":
        await handle_physio_message(user, body_normalized, form_data.get("Body", ""), sender, db)
    elif user.role == "admin":
        await handle_admin_message(user, body_normalized, sender, db)


async def handle_customer_message(user, body, num_media, media_url, sender, db: Session):
    is_payment = False
    if num_media > 0:
        is_payment = True
    elif any(keyword in body for keyword in ["paid", "receipt", "transfer", "fps"]):
        is_payment = True

    if is_payment:
        statement = (
            select(Appointment)
            .where(Appointment.customer_id == user.id, Appointment.status == "scheduled")
            .order_by(Appointment.start_time.desc())
        )
        appt = db.exec(statement).first()

        if appt:
            payment = Payment(
                appointment_id=appt.id,
                amount=500.0,
                payment_method="fps",
                status="pending",
                proof_url=media_url if media_url else "text-confirmation",
            )
            db.add(payment)
            db.commit()

            send_whatsapp_message(sender, "Thank you! We have received your payment proof. We will confirm shortly.")
            notify_admin_of_payment(user, payment, appt)
            return

        send_whatsapp_message(
            sender,
            "Thank you. However, I couldn't find a pending appointment to link this payment to.\n\n"
            "To book, please tell me the duration (30, 45, 60 min) you are interested in.",
        )
        return

    if "min" in body:
        duration = 30
        if "45" in body:
            duration = 45
        elif "60" in body:
            duration = 60

        try:
            available_slots = check_availability(duration)
        except Exception as e:
            debug_log(f"Error checking availability: {e}")
            available_slots = []

        if available_slots:
            slot = available_slots[0]
            user.last_proposed_start = slot
            user.last_proposed_duration = duration
            db.add(user)
            db.commit()

            send_whatsapp_message(
                sender,
                f"Found a slot on {slot.strftime('%Y-%m-%d at %H:%M')}. Reply 'book' if you would like the link to secure this time.",
            )
            return

        send_whatsapp_message(sender, "Sorry, no slots found for the next 3 days. Please try again later.")
        return

    if "book" in body and "booked" not in body:
        from app.services.calendly import get_event_link

        if not user.last_proposed_start:
            send_whatsapp_message(sender, "Please check availability first by mentioning '30 min', '45 min', etc.")
            return

        link = get_event_link(user.last_proposed_duration or 30)
        send_whatsapp_message(
            sender,
            "Please book your slot using this link: "
            f"{link}\n\nIMPORTANT: Once you have completed the booking on the website, reply 'booked' here to proceed with payment.",
        )
        return

    if "booked" in body or "done" in body:
        if not user.last_proposed_start:
            send_whatsapp_message(
                sender,
                "I can't find a pending booking context. Rather than 'booked', please start by saying 'Hi' to find a slot.",
            )
            return

        await confirm_internal_booking(user, sender, db)
        return

    # Check for greetings
    if any(keyword in body for keyword in ["hello", "hi", "hey", "start", "help"]):
        send_whatsapp_message(
            sender,
            "👋 Hello! Welcome to Harry's Physiotherapy booking.\n\n"
            "To book an appointment, please tell me how long you need:\n"
            "• 30 min\n"
            "• 45 min\n"
            "• 60 min"
        )
        return

    send_whatsapp_message(
        sender,
        "I didn't quite catch that. You can say 'Hello' to start, mention a duration like '30 min', or reply 'booked' if you just finished scheduling.",
    )


async def confirm_internal_booking(user, sender, db: Session):
    from datetime import timedelta

    start_time = user.last_proposed_start
    duration = user.last_proposed_duration or 30
    end_time = start_time + timedelta(minutes=duration)

    appt = Appointment(
        customer_id=user.id,
        start_time=start_time,
        end_time=end_time,
        duration_minutes=duration,
        status="scheduled",
        calendly_uuid=f"link-booking-{start_time.strftime('%Y%m%d%H%M')}",
        reminder_sent=False,
    )
    db.add(appt)
    db.commit()

    user.last_proposed_start = None
    db.add(user)
    db.commit()

    send_whatsapp_message(
        sender,
        f"Thank you! we have noted Appointment ID {appt.id} for {start_time}.\nPlease make payment via FPS to ID: 123456 to finalize.",
    )


def notify_admin_of_payment(user, payment, appt) -> None:
    if not ADMIN_PHONE:
        print("ERROR: No ADMIN_PHONE configured")
        return

    msg = (
        "💰 New Payment Received!\n\n"
        f"User: {user.name or user.phone_number}\n"
        f"Amount: ${payment.amount}\n"
        f"Appt ID: {appt.id}\n"
        f"Time: {appt.start_time}\n"
        f"Payment ID: {payment.id}\n\n"
        f"Reply 'approve {payment.id}' to confirm."
    )

    media_urls = None
    if payment.proof_url and "http" in payment.proof_url:
        media_urls = [payment.proof_url]

    send_whatsapp_message(ADMIN_PHONE, msg, media_url=media_urls)


async def handle_note_input(user, body, sender, db: Session):
    from datetime import datetime

    if body.strip().lower() == "done":
        user.conversation_state = "idle"
        db.add(user)
        db.commit()

        statement = (
            select(SessionNote)
            .where(SessionNote.appointment_id == user.active_appointment_id)
            .order_by(SessionNote.created_at)
        )
        notes = db.exec(statement).all()

        send_whatsapp_message(
            sender,
            f"✅ Note-taking completed!\n\nTotal notes saved: {len(notes)}\n\nYou can continue with the session or type 'add notes' again to add more notes.",
        )
        return

    if user.active_appointment_id:
        note = SessionNote(
            appointment_id=user.active_appointment_id,
            note_text=body,
            created_at=datetime.utcnow(),
            created_by="physio",
        )
        db.add(note)
        db.commit()

        timestamp_str = note.created_at.strftime("%H:%M:%S")
        send_whatsapp_message(sender, f"📝 Note saved at {timestamp_str}\n\nContinue adding notes or type 'done' to finish.")
        return

    user.conversation_state = "idle"
    db.add(user)
    db.commit()
    send_whatsapp_message(sender, "Error: No active session found. Exiting note-taking mode.")


async def handle_physio_message(user, body, original_body, sender, db: Session):
    if user.conversation_state == "awaiting_payment_status":
        await handle_payment_status_response(user, body, sender, db)
        return
    if user.conversation_state == "awaiting_payment_method":
        await handle_payment_method_response(user, body, sender, db)
        return
    if user.conversation_state == "adding_notes":
        await handle_note_input(user, original_body, sender, db)
        return

    if "add notes" in body or "add note" in body:
        if user.active_appointment_id:
            appt = db.get(Appointment, user.active_appointment_id)
            if appt and appt.status == "started":
                user.conversation_state = "adding_notes"
                db.add(user)
                db.commit()
                send_whatsapp_message(
                    sender,
                    f"📝 Note-taking mode activated for Session {appt.id}.\n\nType your notes (one message per note). Each note will be timestamped.\n\nType 'done' when finished adding notes.",
                )
                return

        send_whatsapp_message(sender, "No active session found. Please start a session first with 'start <id>'")
        return

    if "view notes" in body:
        try:
            appt_id = int(body.split()[2])
            appt = db.get(Appointment, appt_id)

            if appt:
                statement = select(SessionNote).where(SessionNote.appointment_id == appt_id).order_by(SessionNote.created_at)
                notes = db.exec(statement).all()

                if notes:
                    msg = f"📋 Notes for Session {appt_id}:\n\n"
                    for i, note in enumerate(notes, 1):
                        timestamp = note.created_at.strftime("%Y-%m-%d %H:%M:%S")
                        msg += f"{i}. [{timestamp}]\n{note.note_text}\n\n"
                    msg += f"Total: {len(notes)} note(s)"
                else:
                    msg = f"No notes found for Session {appt_id}"
            else:
                msg = "Appointment not found."
        except (IndexError, ValueError):
            msg = "Usage: view notes <appointment_id>\nExample: view notes 1"

        send_whatsapp_message(sender, msg)
        return

    if "start" in body:
        from datetime import datetime, timedelta

        try:
            appt_id = int(body.split()[1])
            appt = db.get(Appointment, appt_id)
            if appt:
                appt.status = "started"
                appt.start_time = datetime.utcnow()
                appt.end_time = datetime.utcnow() + timedelta(minutes=appt.duration_minutes)
                db.add(appt)

                user.active_appointment_id = appt.id
                db.add(user)
                db.commit()

                statement = select(Payment).where(Payment.appointment_id == appt.id)
                payment = db.exec(statement).first()

                pay_status = "Not Found"
                pay_mode = "Unknown"
                if payment:
                    pay_status = payment.status.capitalize()
                    pay_mode = payment.payment_method.capitalize()

                msg = (
                    f"Session {appt_id} started.\nPayment Status: {pay_status}\nMode: {pay_mode}\n\n"
                    f"Session will auto-complete at {appt.end_time.strftime('%H:%M:%S')} UTC ({appt.duration_minutes} min).\n\n"
                    "💡 You can type 'add notes' during the session to record notes about the client."
                )
            else:
                msg = "Appointment not found."
        except Exception:
            msg = (
                "Please specify appointment ID, e.g., 'start 1'\n\nPhysio Interface:\n"
                "• 'start <id>' - Begin a session\n• 'add notes' - Add notes during session\n"
                "• 'view notes <id>' - View notes for a session\n• 'cancel' - Cancel session"
            )

        send_whatsapp_message(sender, msg)
        return

    if "cancel" in body:
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        send_whatsapp_message(sender, "Session cancelled.")
        return

    send_whatsapp_message(
        sender,
        "Physio Interface:\n• 'start <id>' - Begin a session\n• 'add notes' - Add notes during session\n• 'view notes <id>' - View notes for a session\n• 'cancel' - Cancel session",
    )


async def handle_payment_status_response(user, body, sender, db: Session):
    appt_id = user.active_appointment_id
    appt = db.get(Appointment, appt_id)

    if not appt:
        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        send_whatsapp_message(sender, "Error: Could not find the appointment. Please try again.")
        return

    if "payment received" in body or body == "1" or ("1" in body and "payment" in body):
        user.conversation_state = "awaiting_payment_method"
        db.add(user)
        db.commit()
        send_whatsapp_message(sender, "Great! What payment method was used?\nReply with 'cash' or 'card'")
        return

    if "fps" in body or body == "2":
        appt.physio_payment_status = "fps"
        appt.status = "completed"
        db.add(appt)

        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        send_whatsapp_message(sender, "Recorded: FPS payment. Session completed!")
        return

    if "consolidating" in body or body == "3" or "other session" in body:
        appt.physio_payment_status = "consolidating"
        appt.status = "completed"
        db.add(appt)

        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        send_whatsapp_message(sender, "Recorded: Consolidating with other session. Session completed!")
        return

    send_whatsapp_message(sender, "Please reply with one of the options:\n1️⃣ Payment received\n2️⃣ FPS\n3️⃣ Consolidating with other session")


async def handle_payment_method_response(user, body, sender, db: Session):
    appt_id = user.active_appointment_id
    appt = db.get(Appointment, appt_id)

    if not appt:
        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        send_whatsapp_message(sender, "Error: Could not find the appointment. Please try again.")
        return

    if "cash" in body:
        appt.physio_payment_status = "payment_received"
        appt.physio_payment_method = "cash"
        appt.status = "completed"
        db.add(appt)

        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        send_whatsapp_message(sender, "Cash payment received. Session completed!")
        return

    if "card" in body:
        appt.physio_payment_status = "payment_received"
        appt.physio_payment_method = "card"
        appt.status = "completed"
        db.add(appt)

        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        send_whatsapp_message(sender, "Card payment received. Session completed!")
        return

    send_whatsapp_message(sender, "Please reply with one of the options: 'cash' or 'card'")


async def handle_admin_message(user, body, sender, db: Session):
    if "approve" in body:
        try:
            parts = body.split()
            if len(parts) > 1:
                payment_id = int(parts[1])
                payment = db.get(Payment, payment_id)
            else:
                statement = select(Payment).where(Payment.status == "pending").order_by(Payment.created_at.desc())
                payment = db.exec(statement).first()

            if payment:
                payment.status = "approved"
                db.add(payment)
                db.commit()

                send_whatsapp_message(sender, f"Payment {payment.id} approved.")

                appt = db.get(Appointment, payment.appointment_id)
                customer = db.get(User, appt.customer_id)
                send_whatsapp_message(customer.phone_number, f"✅ Payment Confirmed!\nYour appointment for {appt.start_time} is fully secured.")
                return

            send_whatsapp_message(sender, "No pending payment found to approve.")
        except Exception as e:
            send_whatsapp_message(sender, f"Error approving payment: {e}")
        return

    send_whatsapp_message(sender, "Admin Interface: Reply 'approve <payment_id>' to confirm payments.")
