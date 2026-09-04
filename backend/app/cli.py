"""Admin CLI.

Usage:
    python -m app.cli invite [--label LABEL] [--ttl-days N]
    python -m app.cli purge-sessions
    python -m app.cli whoami
    python -m app.cli delete-user EMAIL
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func, select

from app.db.models.auth import User
from app.db.session import session_scope
from app.services import auth as auth_service


def cmd_invite(args: argparse.Namespace) -> int:
    with session_scope() as db:
        code = auth_service.create_invite(db, label=args.label, ttl_days=args.ttl_days)
    print("\nInvite code (shown once, not recoverable):\n")
    print(f"    {code}\n")
    print(f"Valid for {args.ttl_days} day(s). Redeem it on the sign-up screen.")
    return 0


def cmd_purge_sessions(_: argparse.Namespace) -> int:
    with session_scope() as db:
        n = auth_service.purge_expired_sessions(db)
    print(f"Removed {n} expired session(s).")
    return 0


def cmd_whoami(_: argparse.Namespace) -> int:
    with session_scope() as db:
        total = db.scalar(select(func.count()).select_from(User)) or 0
        users = db.scalars(select(User).order_by(User.created_at)).all()
    print(f"{total} user(s):")
    for u in users:
        flag = " (admin)" if u.is_admin else ""
        state = "" if u.is_active else " [deactivated]"
        print(f"  - {u.email}{flag}{state}")
    return 0


def cmd_delete_user(args: argparse.Namespace) -> int:
    with session_scope() as db:
        user = db.scalar(select(User).where(User.email == args.email.strip().lower()))
        if user is None:
            print(f"No user with email {args.email}.")
            return 1
        db.delete(user)
    print(f"Deleted {args.email}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="app.cli", description="Screener admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_invite = sub.add_parser("invite", help="Mint a new invite code")
    p_invite.add_argument("--label", default=None, help="Note to remember who it is for")
    p_invite.add_argument("--ttl-days", type=int, default=14)
    p_invite.set_defaults(func=cmd_invite)

    sub.add_parser("purge-sessions", help="Delete expired sessions").set_defaults(
        func=cmd_purge_sessions
    )
    sub.add_parser("whoami", help="List users").set_defaults(func=cmd_whoami)

    p_del = sub.add_parser("delete-user", help="Delete a user and their data")
    p_del.add_argument("email")
    p_del.set_defaults(func=cmd_delete_user)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
