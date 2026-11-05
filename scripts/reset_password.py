
import getpass

from sqlalchemy import select

from app.database import SessionLocal
from app.models import User
from app.security import hash_password


def reset_password():
    email = input("Enter account email: ").strip().lower()

    with SessionLocal() as db:
        user = db.scalar(
            select(User).where(User.email == email)
        )

        if user is None:
            print("User not found.")
            return

        new_password = getpass.getpass("New password: ")
        confirm_password = getpass.getpass(
            "Confirm new password: "
        )

        if new_password != confirm_password:
            print("Passwords do not match.")
            return

        if not 8 <= len(new_password) <= 128:
            print("Password must be 8-128 characters.")
            return

        user.password_hash = hash_password(new_password)

        db.commit()

        print("Password reset successfully!")


if __name__ == "__main__":
    reset_password()
