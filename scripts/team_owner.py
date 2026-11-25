import argparse
from getpass import getpass

from fastapi import HTTPException

from app.core import budgets, team


def main():
    parser = argparse.ArgumentParser(description="Create or recover an Orange Team owner from the host.")
    parser.add_argument("handle", help="Team owner's username")
    parser.add_argument("--recover", action="store_true", help="Reset an existing owner's password and revoke their sessions")
    args = parser.parse_args()
    password = getpass("Team owner password: ")
    if password != getpass("Confirm password: "):
        parser.exit(1, "Passwords did not match.\n")
    try:
        team.init_team()
        budgets.init_budgets()
        team.bootstrap_owner(args.handle, password, recover=args.recover)
    except HTTPException as error:
        parser.exit(1, f"{error.detail}\n")
    print("Team owner is ready. Sign in to Orange at /team.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
