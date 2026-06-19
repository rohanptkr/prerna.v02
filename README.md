# Prerna Abhyasika

A production-ready Flask Prerna Abhyasika application built for AWS Elastic Beanstalk with SQLite development support and MySQL/Amazon RDS compatibility.

## Features

- Flask app with Blueprints and SQLAlchemy models
- Admin and Member modules
- Authentication with Flask-Login
- CSRF protection and input validation
- Search, filtering, pagination, CSV export
- Responsive UI with Bootstrap 5
- Production-ready AWS Elastic Beanstalk config

## Project Structure

```
library_management/
├── application.py
├── config.py
├── requirements.txt
├── runtime.txt
├── Procfile
├── .env.example
├── .ebextensions/01_environment.config
├── models/
├── routes/
├── forms/
├── services/
├── templates/
├── static/
├── migrations/
└── README.md
```

## Setup (Local Development)

1. Clone repo and go to project folder:

```bash
cd library_management
```

2. Create Python 3.12 virtualenv and install dependencies:

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

3. Copy environment variables:

```bash
copy .env.example .env
```

4. Initialize database migrations:

```bash
set FLASK_APP=application.py
flask db init
flask db migrate -m "Initial migration"
flask db upgrade
```

5. Seed sample data:

```bash
python seed_sample_data.py
```

6. Run locally:

```bash
flask run
```

## AWS Elastic Beanstalk Deployment

1. Create EB application and environment for Python 3.12.
2. Set environment variables in Elastic Beanstalk:
   - `SECRET_KEY`
   - `DATABASE_URL`
   - `FLASK_ENV=production`
   - `SECURITY_PASSWORD_SALT`
3. Deploy the app using the EB CLI or zipped source bundle.
4. Ensure RDS MySQL string uses `mysql+pymysql://user:pass@host:3306/library_management`.

## Credentials

- Default admin user: `admin@example.com` / `Admin123!`
- Sample role: `Admin`
- Sample role: `Member`

## File References

- `application.py` — app factory, logging, blueprint registration
- `config.py` — environment-based config
- `models/` — database model definitions
- `routes/` — blueprint route handlers
- `forms/` — WTForms definitions
- `templates/` — HTML templates
- `static/` — CSS and JS assets
- `.ebextensions/` — Elastic Beanstalk environment config

## Notes

- Environment variables must be set securely in production.
- Local `DATABASE_URL` falls back to SQLite.
- Migrations are supported via `Flask-Migrate`.
