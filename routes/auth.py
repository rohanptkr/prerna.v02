from datetime import datetime, date
import json
import os
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import urlopen
from flask import Blueprint, flash, redirect, render_template, request, url_for, current_app
from flask_login import current_user, login_user, logout_user

from application import db
from forms.auth_forms import LoginForm, RegistrationForm, ResetPasswordForm
from models import Role, User

auth_bp = Blueprint("auth", __name__, template_folder="../templates")
MAX_FAILED_LOGIN_ATTEMPTS = 5


def _extract_place_query_from_url(place_url):
    if not place_url:
        return ""
    try:
        parsed = urlparse(place_url)
        if "/place/" in parsed.path:
            place_segment = parsed.path.split("/place/", 1)[1].split("/", 1)[0]
            place_name = unquote(place_segment).replace("+", " ").strip()
            if place_name:
                return place_name
        query_params = parse_qs(parsed.query)
        query_term = query_params.get("q", [""])[0].strip()
        if query_term:
            return query_term
    except Exception:
        return ""
    return ""


def _fetch_google_reviews():
    api_key = (current_app.config.get("GOOGLE_MAPS_API_KEY") or "").strip()
    if not api_key:
        return []

    place_id = (current_app.config.get("GOOGLE_MAPS_PLACE_ID") or "").strip()
    place_query = (current_app.config.get("GOOGLE_MAPS_PLACE_QUERY") or "").strip()
    place_url = (current_app.config.get("GOOGLE_MAPS_PLACE_URL") or "").strip()

    if not place_query and place_url:
        place_query = _extract_place_query_from_url(place_url)

    try:
        if not place_id and place_query:
            find_params = urlencode(
                {
                    "input": place_query,
                    "inputtype": "textquery",
                    "fields": "place_id",
                    "key": api_key,
                }
            )
            find_url = f"https://maps.googleapis.com/maps/api/place/findplacefromtext/json?{find_params}"
            with urlopen(find_url, timeout=8) as response:
                find_payload = json.loads(response.read().decode("utf-8"))
            candidates = find_payload.get("candidates") or []
            if candidates:
                place_id = candidates[0].get("place_id", "").strip()

        if not place_id:
            return []

        detail_params = urlencode(
            {
                "place_id": place_id,
                "fields": "reviews,url,name,rating,user_ratings_total",
                "reviews_sort": "newest",
                "key": api_key,
            }
        )
        details_url = f"https://maps.googleapis.com/maps/api/place/details/json?{detail_params}"
        with urlopen(details_url, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))

        place_result = payload.get("result") or {}
        reviews = place_result.get("reviews") or []
        maps_link = place_result.get("url") or place_url

        normalized = []
        for review in reviews[:8]:
            normalized.append(
                {
                    "author_name": review.get("author_name", "Google User"),
                    "rating": int(review.get("rating", 0) or 0),
                    "relative_time_description": review.get("relative_time_description", ""),
                    "text": review.get("text", ""),
                    "profile_photo_url": review.get("profile_photo_url", ""),
                    "maps_link": maps_link,
                }
            )
        return normalized
    except Exception as exc:
        current_app.logger.warning(f"Google reviews fetch failed: {exc}")
        return []


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    form = LoginForm()
    google_reviews = _fetch_google_reviews()
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
            return render_template("auth/login.html", form=form, google_reviews=google_reviews)

        if user and user.is_locked:
            current_app.logger.warning(f"Blocked login attempt for locked account: {email_input}")
            flash("Your account is locked due to multiple failed login attempts. Contact admin.", "danger")
            return render_template("auth/login.html", form=form, google_reviews=google_reviews)

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
                return render_template("auth/login.html", form=form, google_reviews=google_reviews)
            db.session.commit()

        current_app.logger.info(f"Login failed for {email_input}")
        flash("Invalid email or password.", "danger")
    return render_template("auth/login.html", form=form, google_reviews=google_reviews)


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

