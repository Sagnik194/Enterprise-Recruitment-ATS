
from typing import Annotated

from fastapi import APIRouter, Depends

from app.dependencies import (
    get_current_user,
    require_roles,
)
from app.models import User
from app.schemas import UserResponse


router = APIRouter(
    prefix="/users",
    tags=["Users"]
)


@router.get(
    "/me",
    response_model=UserResponse
)
def get_my_profile(
    current_user: Annotated[
        User, Depends(get_current_user)
    ]
):
    return current_user


@router.get("/candidate/dashboard")
def candidate_dashboard(
    current_user: Annotated[
        User, Depends(require_roles("candidate"))
    ]
):
    return {
        "message": "Welcome to Candidate Dashboard",
        "user": current_user.full_name,
        "role": current_user.role
    }


@router.get("/recruiter/dashboard")
def recruiter_dashboard(
    current_user: Annotated[
        User, Depends(require_roles("recruiter"))
    ]
):
    return {
        "message": "Welcome to Recruiter Dashboard",
        "user": current_user.full_name,
        "role": current_user.role
    }


@router.get("/admin/dashboard")
def admin_dashboard(
    current_user: Annotated[
        User, Depends(require_roles("admin"))
    ]
):
    return {
        "message": "Welcome to Admin Dashboard",
        "user": current_user.full_name,
        "role": current_user.role
    }
