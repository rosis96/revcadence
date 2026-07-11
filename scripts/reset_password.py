"""Reset a user's password. Run where DATABASE_URL points at the target DB
(Railway web service shell has it injected).

  /opt/venv/bin/python -m scripts.reset_password --email you@x.com --password "NewStrongPassword"
  /opt/venv/bin/python -m scripts.reset_password --email you@x.com --generate   # prints a random one

Also reactivates the user if they were deactivated. Audit-logged.
"""
import argparse
import secrets

from app.auth import hash_password
from app.db import init_db, session
from app.models.audit import AuditLog
from app.models.identity import Membership, User


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--password", help="new password (min 12 chars)")
    g.add_argument("--generate", action="store_true", help="generate + print a random password")
    args = ap.parse_args()

    password = args.password or secrets.token_urlsafe(14)
    if len(password) < 12:
        raise SystemExit("Password must be at least 12 characters")

    init_db()
    with session() as db:
        user = db.query(User).filter(User.email == args.email.lower().strip()).first()
        if not user:
            raise SystemExit(f"No user with email {args.email!r}")
        user.password_hash = hash_password(password)
        user.active = True
        m = db.query(Membership).filter(Membership.user_id == user.id).first()
        db.add(AuditLog(org_id=m.org_id if m else None, user_id=user.id, action="password_reset"))

    print(f"Password reset for {args.email}")
    if args.generate:
        print(f"NEW PASSWORD: {password}")
    print("Store it in a password manager, then log in at the app root URL.")


if __name__ == "__main__":
    main()
