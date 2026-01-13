from services.twilio_client import send_whatsapp_message
from services.calendly import check_availability, get_current_user_uuid
from models import User, Appointment, Payment
from sqlmodel import Session, select, col
import os

ADMIN_PHONE = os.getenv("ADMIN_PHONE_NUMBER")
PHYSIO_PHONE = os.getenv("PHYSIO_PHONE_NUMBER")

def get_or_create_user(session: Session, phone: str, name: str = None):
    statement = select(User).where(User.phone_number == phone)
    user = session.exec(statement).first()
    
    # Determine expected role based on current Env Vars
    expected_role = "customer"
    if phone == ADMIN_PHONE:
        expected_role = "admin"
    elif phone == PHYSIO_PHONE:
        expected_role = "physio"

    if not user:
        # Create new user
        print(f"DEBUG: Creating new user {phone} as {expected_role}")
        user = User(phone_number=phone, name=name, role=expected_role)
        session.add(user)
        session.commit()
        session.refresh(user)
    else:
        # Update existing user role if it doesn't match config
        if user.role != expected_role:
            print(f"DEBUG: Correcting role for {phone} from {user.role} to {expected_role}")
            user.role = expected_role
            session.add(user)
            session.commit()
            session.refresh(user)
            
    return user

async def process_message(form_data: dict, db: Session):
    """
    Process incoming WhatsApp message.
    """
    sender = form_data.get("From")
    body = form_data.get("Body", "").strip().lower()
    num_media = int(form_data.get("NumMedia", 0))
    media_url = form_data.get("MediaUrl0") # Capture first image if any
    
    user = get_or_create_user(db, sender)
    
    if user.role == "customer":
        await handle_customer_message(user, body, num_media, media_url, sender, db)
    elif user.role == "physio":
        await handle_physio_message(user, body, sender, db)
    elif user.role == "admin":
        await handle_admin_message(user, body, sender, db)

async def handle_customer_message(user, body, num_media, media_url, sender, db: Session):
    # Payment Receipt Handling
    is_payment = False
    if num_media > 0:
        is_payment = True
    elif any(keyword in body for keyword in ["paid", "receipt", "transfer", "fps"]):
        is_payment = True
        
    if is_payment:
        # Find the most recent 'scheduled' appointment for this user that isn't paid yet?
        # For simplicity, we take the last scheduled one.
        statement = select(Appointment).where(
            Appointment.customer_id == user.id,
            Appointment.status == "scheduled"
        ).order_by(Appointment.start_time.desc())
        appt = db.exec(statement).first()
        
        if appt:
            # Create Payment Record
            payment = Payment(
                appointment_id=appt.id,
                amount=500.0, # Mock amount
                payment_method="fps",
                status="pending",
                proof_url=media_url if media_url else "text-confirmation"
            )
            db.add(payment)
            db.commit()
            
            msg = "Thank you! We have received your payment proof. We will confirm shortly."
            send_whatsapp_message(sender, msg)
            
            notify_admin_of_payment(user, payment, appt)
        else:
             msg = "Thank you. However, I couldn't find a pending appointment to link this payment to."
             send_whatsapp_message(sender, msg)
        return

    # Basic conversation flow
    if "hi" in body or "hello" in body:
        msg = "Welcome! efficient physio bookings.\nPlease tell me the date and duration (30, 45, 60 min) you are interested in."
        send_whatsapp_message(sender, msg)
    
    elif "min" in body:
        # Parse duration
        duration = 30
        if "45" in body: duration = 45
        elif "60" in body: duration = 60
        
        # Check availability
        try:
            available_slots = check_availability(duration)
        except Exception as e:
            print(f"Error checking availability: {e}")
            available_slots = []

        if available_slots:
            slot = available_slots[0]
            
            # Save state
            user.last_proposed_start = slot
            user.last_proposed_duration = duration
            db.add(user)
            db.commit()
            
            msg = f"Found a slot on {slot.strftime('%Y-%m-%d at %H:%M')}. Reply 'book' if you would like the link to secure this time."
        else:
            msg = "Sorry, no slots found for the next 3 days. Please try again later."
        
        send_whatsapp_message(sender, msg)
        
    elif "book" in body and "booked" not in body:
        from services.calendly import get_event_link
        
        if not user.last_proposed_start:
             msg = "Please check availability first by mentioning '30 min', '45 min', etc."
             send_whatsapp_message(sender, msg)
             return
             
        link = get_event_link(user.last_proposed_duration or 30)
        
        msg = f"Please book your slot using this link: {link}\n\nIMPORTANT: Once you have completed the booking on the website, reply 'booked' here to proceed with payment."
        send_whatsapp_message(sender, msg)
        
    elif "booked" in body or "done" in body:
        # User claims they finished booking. We create the internal record to track it.
        if not user.last_proposed_start:
             msg = "I can't find a pending booking context. Rather than 'booked', please start by saying 'Hi' to find a slot."
             send_whatsapp_message(sender, msg)
             return

        await confirm_internal_booking(user, sender, db)
        
    else:
        msg = "I didn't quite catch that. You can say 'Hello' to start, mention a duration like '30 min', or reply 'booked' if you just finished scheduling."
        send_whatsapp_message(sender, msg)

async def confirm_internal_booking(user, sender, db: Session):
    from datetime import datetime, timedelta

    start_time = user.last_proposed_start
    duration = user.last_proposed_duration or 30
    end_time = start_time + timedelta(minutes=duration)
    
    # Save to DB
    appt = Appointment(
        customer_id=user.id,
        start_time=start_time,
        end_time=end_time,
        duration_minutes=duration,
        status="scheduled",
        calendly_uuid=f"link-booking-{start_time.strftime('%Y%m%d%H%M')}",
        reminder_sent=False
    )
    db.add(appt)
    db.commit()
    
    # Clear state
    user.last_proposed_start = None
    db.add(user)
    db.commit()
    
    msg = f"Thank you! we have noted Appointment ID {appt.id} for {start_time}.\nPlease make payment via FPS to ID: 123456 to finalize."
    send_whatsapp_message(sender, msg)

def notify_admin_of_payment(user, payment, appt):
    if not ADMIN_PHONE:
        print("ERROR: No ADMIN_PHONE configured")
        return

    msg = f"💰 New Payment Received!\n\nUser: {user.name or user.phone_number}\nAmount: ${payment.amount}\nAppt ID: {appt.id}\nTime: {appt.start_time}\nPayment ID: {payment.id}\n\nReply 'approve {payment.id}' to confirm."
    
    media_url = None
    if payment.proof_url and "http" in payment.proof_url:
        media_url = [payment.proof_url]
        
    send_whatsapp_message(ADMIN_PHONE, msg, media_url=media_url)

async def handle_physio_message(user, body, sender, db: Session):
    # Check if physio is in a payment flow conversation
    if user.conversation_state == "awaiting_payment_status":
        await handle_payment_status_response(user, body, sender, db)
        return
    elif user.conversation_state == "awaiting_payment_method":
        await handle_payment_method_response(user, body, sender, db)
        return
        
    if "start" in body:
        # Extract ID (e.g. 'start 1')
        from datetime import datetime, timedelta
        try:
            appt_id = int(body.split()[1])
            appt = db.get(Appointment, appt_id)
            if appt:
                # Update status and recalculate end_time from NOW
                appt.status = "started"
                appt.start_time = datetime.utcnow()  # Track actual start
                appt.end_time = datetime.utcnow() + timedelta(minutes=1)
                db.add(appt)
                db.commit()
                
                # Check Payment Status
                statement = select(Payment).where(Payment.appointment_id == appt.id)
                payment = db.exec(statement).first()
                
                pay_status = "Not Found"
                pay_mode = "Unknown"
                if payment:
                    pay_status = payment.status.capitalize()
                    pay_mode = payment.payment_method.capitalize()
                
                msg = f"Session {appt_id} started.\nPayment Status: {pay_status}\nMode: {pay_mode}\n\nSession will auto-complete at {appt.end_time.strftime('%H:%M:%S')} UTC ({appt.duration_minutes} min)."
            else:
                msg = "Appointment not found."
        except:
             msg = "Please specify appointment ID, e.g., 'start 1'"
             
        send_whatsapp_message(sender, msg)   
    elif "cancel" in body:
        msg = "Session cancelled."
        send_whatsapp_message(sender, msg)
    else:
        msg = "Physio Interface: Reply 'start <id>' to begin a session or 'cancel' to cancel."
        send_whatsapp_message(sender, msg)

async def handle_payment_status_response(user, body, sender, db: Session):
    # Handle physio's response about payment status after session ends
    appt_id = user.active_appointment_id
    appt = db.get(Appointment, appt_id)
    
    if not appt:
        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        msg = "Error: Could not find the appointment. Please try again."
        send_whatsapp_message(sender, msg)
        return
    
    if "payment received" in body or body == "1" or "1" in body and "payment" in body:
        # Payment received - ask for method
        user.conversation_state = "awaiting_payment_method"
        db.add(user)
        db.commit()
        
        msg = "Great! What payment method was used?\nReply with 'cash' or 'card'"
        send_whatsapp_message(sender, msg)
        
    elif "fps" in body or body == "2":
        # FPS payment
        appt.physio_payment_status = "fps"
        appt.status = "completed"
        db.add(appt)
        
        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        
        msg = "Recorded: FPS payment. Session completed!"
        send_whatsapp_message(sender, msg)
        
    elif "consolidating" in body or body == "3" or "other session" in body:
        # Consolidating with other session
        appt.physio_payment_status = "consolidating"
        appt.status = "completed"
        db.add(appt)
        
        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        
        msg = "Recorded: Consolidating with other session. Session completed!"
        send_whatsapp_message(sender, msg)
        
    else:
        msg = "Please reply with one of the options:\n1️⃣ Payment received\n2️⃣ FPS\n3️⃣ Consolidating with other session"
        send_whatsapp_message(sender, msg)

async def handle_payment_method_response(user, body, sender, db: Session):
    """Handle physio's response about payment method (cash or card)"""
    appt_id = user.active_appointment_id
    appt = db.get(Appointment, appt_id)
    
    if not appt:
        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        msg = "Error: Could not find the appointment. Please try again."
        send_whatsapp_message(sender, msg)
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
        
        msg = "Cash payment received. Session completed!"
        send_whatsapp_message(sender, msg)
        
    elif "card" in body:
        appt.physio_payment_status = "payment_received"
        appt.physio_payment_method = "card"
        appt.status = "completed"
        db.add(appt)
        
        user.conversation_state = "idle"
        user.active_appointment_id = None
        db.add(user)
        db.commit()
        
        msg = "Card payment received. Session completed!"
        send_whatsapp_message(sender, msg)
        
    else:
        msg = "Please reply with one of the options: 'cash' or 'card'"
        send_whatsapp_message(sender, msg)

async def handle_admin_message(user, body, sender, db: Session):
    if "approve" in body:
        # Parse 'approve <id>'
        try:
            parts = body.split()
            if len(parts) > 1:
                payment_id = int(parts[1])
                payment = db.get(Payment, payment_id)
            else:
                # Find latest pending payment
                statement = select(Payment).where(Payment.status == "pending").order_by(Payment.created_at.desc())
                payment = db.exec(statement).first()
            
            if payment:
                payment.status = "approved"
                db.add(payment)
                db.commit()
                
                msg = f"Payment {payment.id} approved."
                send_whatsapp_message(sender, msg)
                
                # Notify User
                appt = db.get(Appointment, payment.appointment_id)
                customer = db.get(User, appt.customer_id)
                user_msg = f"✅ Payment Confirmed!\nYour appointment for {appt.start_time} is fully secured."
                send_whatsapp_message(customer.phone_number, user_msg)
            else:
                msg = "No pending payment found to approve."
                send_whatsapp_message(sender, msg)
                
        except Exception as e:
            msg = f"Error approving payment: {e}"
            send_whatsapp_message(sender, msg)
            
    else:
        msg = "Admin Interface: Reply 'approve <payment_id>' to confirm payments."
        send_whatsapp_message(sender, msg)
