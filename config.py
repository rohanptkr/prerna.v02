import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key")
    FLASK_ENV = os.getenv("FLASK_ENV", "development")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    ITEMS_PER_PAGE = 12
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", "change-this-salt")
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
    GOOGLE_MAPS_PLACE_ID = os.getenv("GOOGLE_MAPS_PLACE_ID", "")
    GOOGLE_MAPS_PLACE_QUERY = os.getenv("GOOGLE_MAPS_PLACE_QUERY", "Prerna Library Akola")
    GOOGLE_MAPS_PLACE_URL = os.getenv("GOOGLE_MAPS_PLACE_URL", "")

    if not SQLALCHEMY_DATABASE_URI:
        raise RuntimeError("DATABASE_URL environment variable is required.")
