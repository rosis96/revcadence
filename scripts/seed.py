"""Create the master organization and the first owner user.

Usage (local or Railway shell):
    python -m scripts.seed --org "Ascendly" --email you@ascendly.one --password <strong-pw>
Idempotent: re-running updates nothing and never duplicates.
"""
import argparse

from app.auth import hash_password
from app.db import init_db, session
from app.models.identity import Membership, Organization, User


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--org", required=True)
    ap.add_argument("--email", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--name", default="")
    args = ap.parse_args()

    init_db()
    with session() as db:
        slug = "".join(c if c.isalnum() else "-" for c in args.org.lower()).strip("-")
        org = db.query(Organization).filter(Organization.slug == slug).first()
        if not org:
            org = Organization(name=args.org, slug=slug)
            db.add(org)
            db.flush()
            print(f"created organization '{args.org}' (id={org.id})")
        email = args.email.lower().strip()
        user = db.query(User).filter(User.email == email).first()
        if not user:
            user = User(email=email, name=args.name or email.split("@")[0],
                        password_hash=hash_password(args.password))
            db.add(user)
            db.flush()
            print(f"created user {email} (id={user.id})")
        if not db.query(Membership).filter(Membership.user_id == user.id, Membership.org_id == org.id).first():
            db.add(Membership(user_id=user.id, org_id=org.id, role="owner", workspace_ids=[]))
            print(f"made {email} OWNER of '{args.org}'")
    print("seed complete — log in via POST /api/auth/login")


if __name__ == "__main__":
    main()
