#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$APP_DIR/venv"
FLASK_APP_FILE="application.py"

echo "=== Change User Credentials ==="

if [[ ! -f "$VENV_PATH/bin/activate" ]]; then
  echo "Error: Virtual environment not found at $VENV_PATH"
  echo "If your venv is elsewhere, edit VENV_PATH inside this script."
  exit 1
fi

read -rp "User email or username: " lookup_value
lookup_value="$(echo "$lookup_value" | xargs)"

if [[ "$lookup_value" == *"@"* ]]; then
  lookup_type="email"
  lookup_value="$(echo "$lookup_value" | tr '[:upper:]' '[:lower:]')"
else
  lookup_type="username"
fi

if [[ -z "$lookup_value" ]]; then
  echo "Error: lookup value cannot be empty."
  exit 1
fi

read -rp "New email (leave blank to keep unchanged): " new_email
new_email="$(echo "$new_email" | tr '[:upper:]' '[:lower:]' | xargs)"

read -rsp "New password: " new_password
echo
read -rsp "Confirm new password: " new_password_confirm
echo

if [[ "$new_password" != "$new_password_confirm" ]]; then
  echo "Error: passwords do not match."
  exit 1
fi

if [[ ${#new_password} -lt 8 ]]; then
  echo "Error: password must be at least 8 characters."
  exit 1
fi

cd "$APP_DIR"
source "$VENV_PATH/bin/activate"
export FLASK_APP="$FLASK_APP_FILE"

# Ensure DATABASE_URL is available for application config.
if [[ -z "${DATABASE_URL:-}" ]]; then
  db_line=""
  if [[ -f "/run/gunicorn/runtime_env" ]]; then
    db_line="$(grep -m1 '^DATABASE_URL=' /run/gunicorn/runtime_env || true)"
  fi

  if [[ -z "$db_line" && -f "$APP_DIR/.env" ]]; then
    db_line="$(grep -m1 '^DATABASE_URL=' "$APP_DIR/.env" || true)"
  fi

  if [[ -n "$db_line" ]]; then
    export DATABASE_URL="${db_line#DATABASE_URL=}"
  fi
fi

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "Error: DATABASE_URL is not set."
  echo "Set it in /run/gunicorn/runtime_env or $APP_DIR/.env and retry."
  exit 1
fi

LOOKUP_TYPE="$lookup_type" LOOKUP_VALUE="$lookup_value" NEW_EMAIL="$new_email" NEW_PASSWORD="$new_password" python3 - <<'PY'
import os
from application import create_app, db
from models import User

lookup_type = os.environ["LOOKUP_TYPE"]
lookup_value = os.environ["LOOKUP_VALUE"]
new_email = os.environ.get("NEW_EMAIL", "").strip().lower()
new_password = os.environ["NEW_PASSWORD"]

app = create_app()
with app.app_context():
    if lookup_type == "email":
        user = User.query.filter_by(email=lookup_value).first()
    else:
        user = User.query.filter_by(username=lookup_value).first()

    if not user:
        print("Error: user not found.")
        raise SystemExit(1)

    if new_email:
        existing = User.query.filter_by(email=new_email).first()
        if existing and existing.id != user.id:
            print("Error: new email already belongs to another user.")
            raise SystemExit(1)
        user.email = new_email

    user.set_password(new_password)

    # Safety reset if account was locked due to failed attempts.
    if hasattr(user, "failed_login_attempts"):
        user.failed_login_attempts = 0
    if hasattr(user, "is_locked"):
        user.is_locked = False
    user.is_active = True

    db.session.commit()
    print(f"Success: credentials updated for user '{user.username}' ({user.email}).")
PY

echo "Done."
