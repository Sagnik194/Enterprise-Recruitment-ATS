
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.schemas import (
    UserRegister,
    UserResponse,
    TokenResponse,
    MessageResponse,
)
from app.security import (
    hash_password,
    verify_password,
    create_access_token,
)


router = APIRouter(
    prefix="/auth",
    tags=["Authentication"]
)


# ==========================================
# REGISTER NEW CANDIDATE
# ==========================================

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
def register(
    data: UserRegister,
    db: Annotated[Session, Depends(get_db)]
):
    email = str(data.email).strip().lower()

    # Check whether email already exists
    existing_user = db.scalar(
        select(User).where(User.email == email)
    )

    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="Email already registered"
        )

    # Public API registration creates
    # candidate accounts only.
    # Recruiters register through /register
    # and require administrator approval.
    new_user = User(
        full_name=data.full_name.strip(),
        email=email,
        password_hash=hash_password(data.password),
        role="candidate",
        approval_status="approved"
    )

    db.add(new_user)

    try:
        db.commit()

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=409,
            detail="Email already registered"
        )

    db.refresh(new_user)

    return new_user


# ==========================================
# LOGIN
# ==========================================

@router.post(
    "/login",
    response_model=TokenResponse
)
def login(
    form_data: Annotated[
        OAuth2PasswordRequestForm,
        Depends()
    ],
    db: Annotated[Session, Depends(get_db)]
):
    email = form_data.username.strip().lower()

    user = db.scalar(
        select(User).where(User.email == email)
    )

    # Verify credentials
    if user is None or not verify_password(
        form_data.password,
        user.password_hash
    ):
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={
                "WWW-Authenticate": "Bearer"
            }
        )

    # ======================================
    # PHASE 11: RECRUITER APPROVAL CHECK
    # ======================================

    if user.role == "recruiter":

        if user.approval_status == "pending":
            raise HTTPException(
                status_code=403,
                detail=(
                    "Your recruiter account is pending "
                    "administrator approval."
                )
            )

        if user.approval_status == "rejected":
            raise HTTPException(
                status_code=403,
                detail=(
                    "Your recruiter registration "
                    "has been rejected."
                )
            )

        if user.approval_status != "approved":
            raise HTTPException(
                status_code=403,
                detail="Recruiter account is not approved"
            )

    # Generate JWT token
    token = create_access_token(user.id)

    return {
        "access_token": token,
        "token_type": "bearer"
    }


# ==========================================
# LOGOUT
# ==========================================

@router.post(
    "/logout",
    response_model=MessageResponse
)
def logout():
    return {
        "message": (
            "Remove the access token from your client. "
            "It remains valid until expiration."
        )
    }
