#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${1:-/home/ec2-user/download/library_management}"

cd "$APP_DIR"

git fetch origin
git checkout attendancefix
git pull --ff-only origin attendancefix

if [[ ! -f venv/bin/activate ]]; then
  python3 -m venv venv
fi

source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

read -rp "DB host: " DB_HOST
read -rp "DB port [3306]: " DB_PORT
DB_PORT="${DB_PORT:-3306}"
read -rp "DB name: " DB_NAME
read -rp "DB user: " DB_USER
read -srp "DB password: " DB_PASS
echo

DB_PASS_ENC="$(python3 -c "import urllib.parse,sys; print(urllib.parse.quote_plus(sys.argv[1]))" "$DB_PASS")"

export FLASK_APP=application.py
export DATABASE_URL="mysql+pymysql://${DB_USER}:${DB_PASS_ENC}@${DB_HOST}:${DB_PORT}/${DB_NAME}"

flask db upgrade

sudo systemctl restart gunicorn
sudo systemctl restart nginx
sudo systemctl status gunicorn --no-pager -l

echo "Deploy complete on attendancefix."
