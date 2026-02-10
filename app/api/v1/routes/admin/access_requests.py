"""Admin endpoints for managing access requests."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.core.auth import get_current_admin
from app.db.session import get_session
from app.models import AccessRequest, Therapist, User
from app.api.v1.schemas.access_request import (
    AccessRequestListResponse,
    AccessRequestApprove,
    AccessRequestApproveResponse,
)

router = APIRouter(prefix="/admin/access-requests", tags=["Admin - Access Requests"])


@router.get("", response_model=list[AccessRequestListResponse])
def list_access_requests(
    status: str | None = None,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """
    List access requests.

    Optionally filter by status: pending, approved, rejected.
    Defaults to showing only pending requests.
    """
    query = select(AccessRequest).order_by(AccessRequest.requested_at.desc())

    if status:
        query = query.where(AccessRequest.status == status)
    else:
        # Default: show only pending
        query = query.where(AccessRequest.status == "pending")

    requests = db.exec(query).all()

    return [
        AccessRequestListResponse(
            id=req.id,
            neon_auth_sub=req.neon_auth_sub,
            email=req.email,
            status=req.status,
            requested_at=req.requested_at,
            reviewed_at=req.reviewed_at,
        )
        for req in requests
    ]


@router.post("/{request_id}/approve", response_model=AccessRequestApproveResponse, status_code=201)
def approve_access_request(
    request_id: int,
    data: AccessRequestApprove,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """
    Approve an access request and create User + Therapist records.

    Creates both User and Therapist records atomically.
    """
    # Get access request
    access_request = db.get(AccessRequest, request_id)
    if not access_request:
        raise HTTPException(status_code=404, detail="Access request not found")

    if access_request.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Access request already {access_request.status}",
        )

    # Check if user already exists (shouldn't happen, but safety check)
    existing_user = db.exec(
        select(User).where(User.neon_auth_sub == access_request.neon_auth_sub)
    ).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="User already exists")

    # Create User record
    user = User(
        neon_auth_sub=access_request.neon_auth_sub,
        email=access_request.email,
        display_name=data.display_name or access_request.email.split("@")[0],  # Default to email prefix
        role=data.role,
        is_active=True,
    )
    db.add(user)
    db.flush()  # Get user.id

    # Create Therapist record if role is therapist
    therapist = None
    if data.role == "therapist":
        therapist = Therapist(
            user_id=user.id,
            display_name=user.display_name,
            is_active=False,  # Will be activated after onboarding
        )
        db.add(therapist)
        db.flush()

    # Mark access request as approved
    access_request.status = "approved"
    access_request.reviewed_at = datetime.now(timezone.utc)
    access_request.reviewed_by = admin.id
    db.add(access_request)

    db.commit()
    db.refresh(user)
    if therapist:
        db.refresh(therapist)

    return AccessRequestApproveResponse(
        access_request_id=access_request.id,
        user_id=user.id,
        therapist_id=therapist.id if therapist else None,
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        message="Access approved. User can now complete onboarding." if therapist else "Access approved.",
    )


@router.post("/{request_id}/reject", status_code=204)
def reject_access_request(
    request_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_session),
):
    """
    Reject an access request.

    Does not create User record. User will see "Access denied" on next login attempt.
    """
    access_request = db.get(AccessRequest, request_id)
    if not access_request:
        raise HTTPException(status_code=404, detail="Access request not found")

    if access_request.status != "pending":
        raise HTTPException(
            status_code=400,
            detail=f"Access request already {access_request.status}",
        )

    # Mark as rejected
    access_request.status = "rejected"
    access_request.reviewed_at = datetime.now(timezone.utc)
    access_request.reviewed_by = admin.id
    db.add(access_request)
    db.commit()

    return None
