from datetime import datetime
import os
from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_user, logout_user

from application import db
from forms.auth_forms import LoginForm, RegistrationForm, ResetPasswordForm
from models import Role, User

auth_bp = Blueprint("auth", __name__, template_folder="../templates")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = LoginForm()
    # If a POST was made but validation failed, log form errors for debugging
    if request.method == "POST" and not form.validate():
        current_app.logger.info(f"Login form validation failed: {form.errors}")

    if form.validate_on_submit():
        email_input = form.email.data.lower()
        current_app.logger.info(f"Login attempt for {email_input}")
        # Log DB URI and user count to verify which DB the worker is using
        try:
            db_uri = current_app.config.get('SQLALCHEMY_DATABASE_URI')
            cwd = os.getcwd()
            resolved_db_path = None
            db_exists = False
            db_size = None
            if db_uri and isinstance(db_uri, str) and db_uri.startswith('sqlite:///'):
                db_rel = db_uri.replace('sqlite:///', '')
                if os.path.isabs(db_rel):
                    resolved_db_path = db_rel
                else:
                    resolved_db_path = os.path.join(cwd, db_rel)
                db_exists = os.path.exists(resolved_db_path)
                if db_exists:
                    try:
                        db_size = os.path.getsize(resolved_db_path)
                    except Exception:
                        db_size = None
            user_count = User.query.count()
        except Exception as e:
            db_uri = f"error: {e}"
            user_count = 'error'
            cwd = 'error'
            resolved_db_path = 'error'
            db_exists = 'error'
            db_size = 'error'
        current_app.logger.info(f"DB URI: {db_uri} | resolved_db_path: {resolved_db_path} | exists: {db_exists} | size: {db_size} | users_in_db: {user_count} | cwd: {cwd}")
        user = User.query.filter_by(email=email_input).first()
        password_ok = user.check_password(form.password.data) if user else False
        current_app.logger.info(
            f"Login lookup: user_found={bool(user)}, password_ok={password_ok}, is_active={getattr(user, 'is_active', None)}"
        )
        if user and password_ok and user.is_active:
            current_app.logger.info(f"Login success for {email_input}")
            login_user(user, remember=form.remember_me.data)
            user.last_login = datetime.utcnow()
            db.session.commit()
            flash("Logged in successfully.", "success")
            next_page = request.args.get("next") or url_for("main.index")
            return redirect(next_page)
        current_app.logger.info(f"Login failed for {email_input}")
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html", form=form)


@auth_bp.route("/logout")
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    form = RegistrationForm()
    if form.validate_on_submit():
        existing = User.query.filter((User.username == form.username.data) | (User.email == form.email.data.lower())).first()
        if existing:
            flash("Username or email already exists.", "warning")
        else:
            role = Role.query.filter_by(role_name="Member").first()
            if not role:
                role = Role(role_name="Member", description="Standard member role")
                db.session.add(role)
                db.session.commit()
            user = User(
                username=form.username.data,
                email=form.email.data.lower(),
                role=role,
            )
            user.set_password(form.password.data)
            db.session.add(user)
            db.session.commit()
            flash("Account created successfully. Please log in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("auth/register.html", form=form)


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data.lower()).first()
        if user:
            flash("Password reset instructions would be sent to your email in production.", "info")
        else:
            flash("If an account exists with that email, instructions will be sent.", "info")
        return redirect(url_for("auth.login"))
    return render_template("auth/reset_password.html", form=form)

