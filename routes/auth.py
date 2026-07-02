from datetime import datetime, date
import os
from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_user, logout_user

from application import db
from forms.auth_forms import LoginForm, RegistrationForm, ResetPasswordForm
from models import Role, User

auth_bp = Blueprint("auth", __name__, template_folder="../templates")
MAX_FAILED_LOGIN_ATTEMPTS = 5


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
            user_count = User.query.count()
        except Exception as e:
            db_uri = f"error: {e}"
            user_count = 'error'
            cwd = 'error'
        current_app.logger.info(f"DB URI: {db_uri} | users_in_db: {user_count} | cwd: {cwd}")
        user = User.query.filter_by(email=email_input).first()
        if user and user.member and user.member.membership_end_date and user.member.membership_end_date < date.today():
            user.member.membership_status = "Expired"
            user.is_active = False
            db.session.commit()
            current_app.logger.info(f"Blocked login for expired member account: {email_input}")
            flash("Membership has expired. Please contact admin to renew access.", "danger")
            return render_template("auth/login.html", form=form)

        if user and user.is_locked:
            current_app.logger.warning(f"Blocked login attempt for locked account: {email_input}")
            flash("Your account is locked due to multiple failed login attempts. Contact admin.", "danger")
            return render_template("auth/login.html", form=form)

        password_ok = user.check_password(form.password.data) if user else False
        current_app.logger.info(
            f"Login lookup: user_found={bool(user)}, password_ok={password_ok}, "
            f"is_active={getattr(user, 'is_active', None)}, is_locked={getattr(user, 'is_locked', None)}, "
            f"failed_login_attempts={getattr(user, 'failed_login_attempts', None)}"
        )
        if user and password_ok and user.is_active and not user.is_locked:
            current_app.logger.info(f"Login success for {email_input}")
            login_user(user, remember=form.remember_me.data)
            user.last_login = datetime.utcnow()
            user.failed_login_attempts = 0
            db.session.commit()
            flash("Logged in successfully.", "success")
            next_page = request.args.get("next") or url_for("main.index")
            return redirect(next_page)

        if user:
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= MAX_FAILED_LOGIN_ATTEMPTS:
                user.is_locked = True
                db.session.commit()
                current_app.logger.warning(f"Account locked after failed logins: {email_input}")
                flash("Your account is locked due to multiple failed login attempts. Contact admin.", "danger")
                return render_template("auth/login.html", form=form)
            db.session.commit()

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

