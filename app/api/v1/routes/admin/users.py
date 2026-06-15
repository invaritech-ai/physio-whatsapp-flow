"""Admin endpoints for user management (role changes)."""

from datetime import datetime, timezone
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, func, select

from app.core.auth import (
    get_current_admin,
    is_bot_only_suspend_email,
    revoke_user_sessions,
)
from app.db.session import get_session
from app.models import Therapist, User
from app.services.auth_audit import record_auth_event
from app.api.v1.schemas.user import (
    RevokeSessionsRequest,
    RevokeSessionsResponse,
    UpdateRoleRequest,
    UpdateRoleResponse,
    UpdateUserStatusRequest,
    UpdateUserStatusResponse,
    UserListResponse,
)

router = APIRouter(prefix="/admin/users", tags=["Admin - Users"])
logger = logging.getLogger("app.auth")


def _active_admin_count(db: Session) -> int:
    return db.exec(
        select(func.count(User.id)).where(
            User.role == "admin",
            User.is_active == True,  # noqa: E712
        )
    ).one()


@router.get("", response_model=list[UserListResponse])
def list_users(
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """List all approved users with their current roles."""
    users = db.exec(select(User).order_by(User.created_at.desc())).all()
    user_ids = [user.id for user in users if user.id is not None]
    therapist_user_ids: set[int] = set()
    if user_ids:
        therapist_user_ids = set(
            db.exec(
                select(Therapist.user_id).where(  # type: ignore[arg-type]
                    Therapist.user_id.in_(user_ids)
                )
            ).all()
        )

    result = []
    for user in users:
        result.append(
            UserListResponse(
                id=user.id,
                email=user.email,
                display_name=user.display_name,
                role=user.role,
                is_active=user.is_active,
                has_therapist_profile=(user.id in therapist_user_ids),
                created_at=user.created_at,
            )
        )

    return result


@router.patch("/{user_id}/role", response_model=UpdateRoleResponse)
def update_user_role(
    user_id: int,
    data: UpdateRoleRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """
    Change a user's role between 'admin' and 'therapist'.

    Transactional rules:
    - Cannot demote the last active admin
    - admin → therapist: creates Therapist profile if none exists, reactivates if inactive
    - therapist → admin: retains Therapist profile (deactivated)
    """
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    previous_role = target_user.role

    if previous_role == data.role:
        raise HTTPException(
            status_code=400,
            detail=f"User already has role '{data.role}'",
        )

    # Prevent demoting the last active admin
    if previous_role == "admin" and data.role == "therapist":
        if _active_admin_count(db) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot demote the last active admin",
            )

    therapist_id = None

    if data.role == "therapist":
        # admin → therapist: ensure Therapist profile exists
        therapist = db.exec(
            select(Therapist).where(Therapist.user_id == target_user.id)
        ).first()

        if therapist:
            # Reactivate existing profile
            therapist.is_active = True
            therapist.display_name = target_user.display_name
            db.add(therapist)
        else:
            # Create new Therapist profile
            therapist = Therapist(
                user_id=target_user.id,
                display_name=target_user.display_name,
                is_active=False,  # Needs onboarding before activation
            )
            db.add(therapist)
            db.flush()

        therapist_id = therapist.id

    elif data.role == "admin":
        # therapist → admin: deactivate Therapist profile (retain data)
        therapist = db.exec(
            select(Therapist).where(Therapist.user_id == target_user.id)
        ).first()
        if therapist:
            therapist.is_active = False
            db.add(therapist)

    # Update the user's role
    target_user.role = data.role
    target_user.updated_at = datetime.now(timezone.utc)
    revoke_user_sessions(
        target_user,
        reason=f"role_change:{previous_role}->{data.role}",
        actor_user_id=admin.id,
        db=db,
    )
    record_auth_event(
        db,
        event_type="role_change",
        user_id=target_user.id,
        actor_user_id=admin.id,
        reason=f"{previous_role}->{data.role}",
        details={
            "previous_role": previous_role,
            "new_role": data.role,
        },
        commit=False,
    )
    db.add(target_user)
    db.commit()
    db.refresh(target_user)

    logger.info(
        "auth.role_change %s",
        json.dumps(
            {
                "actor_user_id": admin.id,
                "target_user_id": target_user.id,
                "previous_role": previous_role,
                "new_role": target_user.role,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ),
    )

    return UpdateRoleResponse(
        user_id=target_user.id,
        email=target_user.email,
        previous_role=previous_role,
        new_role=target_user.role,
        therapist_id=therapist_id,
        message=f"Role changed from '{previous_role}' to '{data.role}'",
    )


def _update_bot_only_suspension(
    *,
    target_user: User,
    therapist: Therapist,
    desired_active: bool,
    admin: User,
    db: Session,
) -> UpdateUserStatusResponse:
    """Apply suspension as a WhatsApp-bot-only removal.

    Toggles only ``therapist.is_active`` (suspend -> False removes them from the
    bot's ``Therapist.is_active == True`` filters; reactivate -> True restores
    them). The User account stays active and sessions are NOT revoked, so the
    therapist keeps login and full dashboard access (``get_current_therapist``
    skips the inactive-profile deny for these accounts).
    """
    if therapist.is_active == desired_active:
        raise HTTPException(
            status_code=400,
            detail=(
                "Therapist already active in the WhatsApp bot"
                if desired_active
                else "Therapist already removed from the WhatsApp bot"
            ),
        )

    therapist.is_active = desired_active
    db.add(therapist)
    target_user.updated_at = datetime.now(timezone.utc)
    db.add(target_user)

    record_auth_event(
        db,
        event_type="account_status_change",
        user_id=target_user.id,
        actor_user_id=admin.id,
        reason=f"bot_only:therapist_active={desired_active}",
        details={
            "bot_only_suspension": True,
            "therapist_is_active_set_to": desired_active,
            "user_is_active": target_user.is_active,
        },
        commit=False,
    )
    db.commit()
    db.refresh(target_user)

    logger.info(
        "auth.bot_only_suspend %s",
        json.dumps(
            {
                "actor_user_id": admin.id,
                "target_user_id": target_user.id,
                "therapist_is_active": desired_active,
                "user_is_active": target_user.is_active,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ),
    )

    return UpdateUserStatusResponse(
        user_id=target_user.id,
        email=target_user.email,
        previous_is_active=target_user.is_active,
        new_is_active=target_user.is_active,
        message=(
            "Therapist restored to the WhatsApp bot (login retained)"
            if desired_active
            else "Therapist removed from the WhatsApp bot (login retained)"
        ),
    )


@router.patch("/{user_id}/status", response_model=UpdateUserStatusResponse)
def update_user_status(
    user_id: int,
    data: UpdateUserStatusRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Activate or suspend a user account and revoke current sessions."""
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    # Bot-only suspension: for designated therapist accounts, suspending must
    # only remove them from the WhatsApp bot while leaving login and dashboard
    # access intact. Reactivation restores them to the bot.
    if is_bot_only_suspend_email(target_user.email):
        therapist = db.exec(
            select(Therapist).where(Therapist.user_id == target_user.id)
        ).first()
        if therapist is not None:
            return _update_bot_only_suspension(
                target_user=target_user,
                therapist=therapist,
                desired_active=data.is_active,
                admin=admin,
                db=db,
            )
        # No therapist profile to gate -> fall through to normal handling.

    previous_is_active = target_user.is_active
    if previous_is_active == data.is_active:
        raise HTTPException(
            status_code=400,
            detail=f"User already {'active' if data.is_active else 'inactive'}",
        )

    if target_user.role == "admin" and previous_is_active and not data.is_active:
        if _active_admin_count(db) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Cannot deactivate the last active admin",
            )

    target_user.is_active = data.is_active
    target_user.updated_at = datetime.now(timezone.utc)

    # Cascade to the therapist profile so suspension also removes the
    # therapist from client-facing (WhatsApp bot) flows immediately.
    therapist_profile_change: bool | None = None
    therapist = db.exec(
        select(Therapist).where(Therapist.user_id == target_user.id)
    ).first()
    if therapist:
        if not data.is_active:
            if therapist.is_active:
                therapist.is_active = False
                therapist_profile_change = False
                db.add(therapist)
        elif therapist.calendly_user_uri:
            # Restore bookability only for therapists who completed
            # onboarding; un-onboarded profiles stay inactive until they
            # finish onboarding themselves.
            if not therapist.is_active:
                therapist.is_active = True
                therapist_profile_change = True
                db.add(therapist)

    revoke_user_sessions(
        target_user,
        reason=f"status_change:{previous_is_active}->{data.is_active}",
        actor_user_id=admin.id,
        db=db,
    )
    record_auth_event(
        db,
        event_type="account_status_change",
        user_id=target_user.id,
        actor_user_id=admin.id,
        reason=f"{previous_is_active}->{data.is_active}",
        details={
            "previous_is_active": previous_is_active,
            "new_is_active": data.is_active,
            "therapist_profile_is_active_set_to": therapist_profile_change,
        },
        commit=False,
    )
    db.add(target_user)
    db.commit()
    db.refresh(target_user)

    logger.info(
        "auth.suspend %s",
        json.dumps(
            {
                "actor_user_id": admin.id,
                "target_user_id": target_user.id,
                "previous_is_active": previous_is_active,
                "new_is_active": target_user.is_active,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ),
    )

    return UpdateUserStatusResponse(
        user_id=target_user.id,
        email=target_user.email,
        previous_is_active=previous_is_active,
        new_is_active=target_user.is_active,
        message="User reactivated" if target_user.is_active else "User suspended",
    )


@router.post("/{user_id}/revoke-sessions", response_model=RevokeSessionsResponse)
def revoke_user_active_sessions(
    user_id: int,
    data: RevokeSessionsRequest,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """Manually revoke all active sessions for a user."""
    target_user = db.get(User, user_id)
    if not target_user:
        raise HTTPException(status_code=404, detail="User not found")

    clean_reason = data.reason.strip() if data.reason else None
    if clean_reason == "":
        clean_reason = None

    revoke_reason = "manual_revoke"
    if clean_reason:
        revoke_reason = f"manual_revoke:{clean_reason}"

    revoke_user_sessions(
        target_user,
        reason=revoke_reason,
        actor_user_id=admin.id,
        db=db,
    )
    record_auth_event(
        db,
        event_type="manual_revoke",
        user_id=target_user.id,
        actor_user_id=admin.id,
        reason=clean_reason or "manual_revoke",
        details={"reason": clean_reason},
        commit=False,
    )
    db.add(target_user)
    db.commit()
    db.refresh(target_user)

    logger.info(
        "auth.manual_revoke %s",
        json.dumps(
            {
                "actor_user_id": admin.id,
                "target_user_id": target_user.id,
                "reason": clean_reason,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ),
    )

    return RevokeSessionsResponse(
        user_id=target_user.id,
        email=target_user.email,
        revoked_at=target_user.revoked_at,
        message="User sessions revoked",
    )
