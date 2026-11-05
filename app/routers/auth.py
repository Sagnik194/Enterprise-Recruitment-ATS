
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


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED
)
def register(
    data: UserRegister,
    db: Annotated[Session, Depends(get_db)]
):
    email = str(data.email).lower()

    existing_user = db.scalar(
        select(User).where(User.email == email)
    )

    if existing_user:
        raise HTTPException(
            status_code=409,
            detail="Email already registered"
        )

    new_user = User(
        full_name=data.full_name,
        email=email,
        password_hash=hash_password(data.password),
        role="candidate"
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


@router.post(
    "/login",
    response_model=TokenResponse
)
def login(
    form_data: Annotated[
        OAuth2PasswordRequestForm, Depends()
    ],
    db: Annotated[Session, Depends(get_db)]
):
    email = form_data.username.strip().lower()

    user = db.scalar(
        select(User).where(User.email == email)
    )

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

    token = create_access_token(user.id)

    return {
        "access_token": token,
        "token_type": "bearer"
    }


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
