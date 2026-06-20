import logging
import os
from datetime import timezone
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from flask import Flask
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect

from config import Config

db = SQLAlchemy()
migrate = Migrate()
login_manager = LoginManager()
csrf = CSRFProtect()
IST = ZoneInfo("Asia/Kolkata")


def _to_ist(dt_value):
    if dt_value is None:
        return None
    if dt_value.tzinfo is None:
        dt_value = dt_value.replace(tzinfo=timezone.utc)
    return dt_value.astimezone(IST)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    from models import User

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.member import member_bp
    from routes.main import main_bp
    from routes.api import api_bp
    from routes.daily_seats import daily_seats_bp
    from routes.admissions import admissions_bp
    from routes.attendance import attendance_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(member_bp, url_prefix="/member")
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(daily_seats_bp)
    app.register_blueprint(admissions_bp)
    app.register_blueprint(attendance_bp)

    @app.template_filter("ist_datetime")
    def ist_datetime(value, fmt="%Y-%m-%d %I:%M %p"):
        dt_value = _to_ist(value)
        return dt_value.strftime(fmt) if dt_value else "-"

    @app.template_filter("ist_date")
    def ist_date(value, fmt="%Y-%m-%d"):
        dt_value = _to_ist(value)
        return dt_value.strftime(fmt) if dt_value else "-"

    @app.template_filter("ist_time")
    def ist_time(value, fmt="%I:%M %p"):
        dt_value = _to_ist(value)
        return dt_value.strftime(fmt) if dt_value else "-"

    @app.template_filter("inr")
    def inr(value):
        if value is None:
            return "₹0.00"
        try:
            return f"₹{float(value):,.2f}"
        except (TypeError, ValueError):
            return "₹0.00"

    if not os.path.exists("logs"):
        os.mkdir("logs")

    file_handler = RotatingFileHandler("logs/library_management.log", maxBytes=102400, backupCount=10)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]")
    )
    file_handler.setLevel(logging.INFO)
    app.logger.addHandler(file_handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info("Prerna Abhyasika startup")

    return app


app = create_app()
