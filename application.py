import logging
import os
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from zoneinfo import ZoneInfo

from flask import Flask, request
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

    from models import AuditLog, User
    audit_retention_days = 60

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    @app.after_request
    def log_admin_operations(response):
        from flask_login import current_user

        if request.endpoint == "static":
            return response
        if not current_user.is_authenticated:
            return response

        forwarded_for = request.headers.get("X-Forwarded-For", "")
        ip_address = forwarded_for.split(",", 1)[0].strip() if forwarded_for else request.remote_addr

        try:
            with db.engine.begin() as connection:
                cutoff_utc = datetime.utcnow() - timedelta(days=audit_retention_days)
                connection.execute(
                    AuditLog.__table__.delete().where(AuditLog.created_at < cutoff_utc)
                )
                connection.execute(
                    AuditLog.__table__.insert().values(
                        user_id=current_user.id,
                        method=request.method,
                        endpoint=request.endpoint,
                        path=request.full_path[:255] if request.query_string else request.path,
                        status_code=response.status_code,
                        ip_address=(ip_address or "")[:64] or None,
                    )
                )
        except Exception:
            app.logger.exception("Failed to record audit log")

        return response

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

    @app.context_processor
    def inject_pending_renewal_count():
        """Inject pending renewal count for sidebar badge."""
        from flask_login import current_user
        
        pending_count = 0
        if current_user.is_authenticated and current_user.is_admin:
            from models import RenewalRequest
            try:
                pending_count = RenewalRequest.query.filter_by(status="Pending").count()
            except Exception:
                pending_count = 0
        
        return {"pending_renewal_count": pending_count}

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
