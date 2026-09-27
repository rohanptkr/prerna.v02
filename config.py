import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    PREFERRED_URL_SCHEME = "https"
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    ITEMS_PER_PAGE = 12
    MEMBERSHIP_CYCLE_DAYS = int(os.getenv("MEMBERSHIP_CYCLE_DAYS", "30"))
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "change-this-salt")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    SESSION_COOKIE_SECURE = True
    REMEMBER_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SAMESITE = "Lax"

    if not SQLALCHEMY_DATABASE_URI:
        raise RuntimeError("DATABASE_URL environment variable is required.")
