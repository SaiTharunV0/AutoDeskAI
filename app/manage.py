"""Explicit local administrator bootstrap; never exposed through an API."""
import argparse
from sqlalchemy import select
from app.database import SessionLocal
from app.models import User
from app.workflows import audit
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["promote-admin"])
    parser.add_argument("email")
    args = parser.parse_args()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.email == args.email.lower()))
        if not user:
            raise SystemExit("Register the account first.")
        user.role = "admin"
        audit(db, user.id, "ADMIN_BOOTSTRAPPED", "user", user.id, "COMPLETED")
        db.commit()
        print("Administrator role assigned.")
if __name__ == "__main__":
    main()
