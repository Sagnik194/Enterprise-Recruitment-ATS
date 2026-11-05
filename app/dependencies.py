
from typing import Annotated

import jwt

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models import User


settings = get_settings()

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/auth/login"
)


def credentials_error():
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[Session, Depends(get_db)]
) -> User:

    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]},
        )

        if payload.get("type") != "access":
            raise credentials_error()

        user_id = int(payload["sub"])

        if user_id <= 0:
            raise credentials_error()

    except (
        jwt.InvalidTokenError,
        ValueError,
        TypeError,
        KeyError,
    ):
        raise credentials_error()

    user = db.get(User, user_id)

    if user is None:
        raise credentials_error()

    return user


def require_roles(*allowed_roles: str):

    def role_checker(
        current_user: Annotated[
            User, Depends(get_current_user)
        ]
    ) -> User:

        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission"
            )

        return current_user

    return role_checker
