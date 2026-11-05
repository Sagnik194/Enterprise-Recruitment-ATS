
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in (
        "admin", "recruiter"
    ):
        print(
            "Usage: python -m scripts.create_staff "
            "[admin|recruiter]"
        )
        return

    role = sys.argv[1]

    full_name = input("Full name: ").strip()
    email = input("Email: ").strip().lower()
    password = getpass.getpass("Password: ")

    if (
        len(full_name) < 2
        or "@" not in email
        or len(password) < 8
        or len(password) > 128
    ):
        print("Invalid name, email or password.")
        return

    with SessionLocal() as db:
        existing = db.scalar(
            select(User).where(User.email == email)
        )

        if existing:
            print("Email already exists.")
            return

        user = User(
            full_name=full_name,
            email=email,
            password_hash=hash_password(password),
            role=role,
        )

        db.add(user)

        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            print("Account could not be created.")
            return

        print(f"{role.capitalize()} created successfully.")


if __name__ == "__main__":
    main()
