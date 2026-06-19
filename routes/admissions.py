from datetime import date
from dateutil.relativedelta import relativedelta
from functools import wraps

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from application import db
from models import Member, Role, User

admissions_bp = Blueprint("admissions", __name__, template_folder="../templates")


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role.role_name != "Admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)
    return wrapper


def _generate_member_code():
    count = Member.query.count() + 1
    return f"{count:04d}"


def _create_user_for_member(full_name, email, member_code):
    """Create a user with username = full_name (lowercase) and password = member_code."""
    username = full_name.strip().lower().replace("  ", " ")
    # Ensure unique username
    base = username
    suffix = 1
    while User.query.filter_by(username=username).first():
        username = f"{base}{suffix}"
        suffix += 1

    member_role = Role.query.filter_by(role_name="Member").first()
    if not member_role:
        member_role = Role(role_name="Member", description="Library member")
        db.session.add(member_role)
        db.session.flush()

    user = User(
        username=username,
        email=email.lower(),
        role_id=member_role.id,
        is_active=True,
    )
    user.set_password(member_code)  # 4-digit member code as password
    db.session.add(user)
    db.session.flush()
    return user


@admissions_bp.route("/admissions")
@login_required
@admin_required
def index():
    search = request.args.get("q", "")
    status_filter = request.args.get("status", "")
    page = request.args.get("page", 1, type=int)
    query = Member.query
    if search:
        query = query.filter(
            Member.full_name.ilike(f"%{search}%") |
            Member.member_code.ilike(f"%{search}%") |
            Member.phone.ilike(f"%{search}%")
        )
    if status_filter:
        query = query.filter_by(membership_status=status_filter)
    pagination = query.order_by(Member.registration_date.desc()).paginate(page=page, per_page=15)
    return render_template("admissions/index.html", pagination=pagination, search=search, status_filter=status_filter)


@admissions_bp.route("/admissions/new", methods=["GET", "POST"])
@login_required
@admin_required
def new_admission():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip().lower()
        address = request.form.get("address", "").strip()
        start_date_str = request.form.get("membership_start_date", "")
        duration_months = int(request.form.get("duration_months", 1))

        errors = []
        if not full_name:
            errors.append("Full name is required.")
        if not phone:
            errors.append("Phone is required.")
        if not email:
            errors.append("Email is required.")
        if not address:
            errors.append("Address is required.")
        if User.query.filter_by(email=email).first():
            errors.append("A user with this email already exists.")

        try:
            start_date = date.fromisoformat(start_date_str) if start_date_str else date.today()
        except ValueError:
            start_date = date.today()

        end_date = start_date + relativedelta(months=duration_months)

        if errors:
            for e in errors:
                flash(e, "danger")
            return render_template("admissions/new.html", form=request.form)

        member_code = _generate_member_code()
        user = _create_user_for_member(full_name, email, member_code)

        member = Member(
            member_code=member_code,
            full_name=full_name,
            phone=phone,
            email=email,
            address=address,
            membership_start_date=start_date,
            membership_end_date=end_date,
            membership_status="Active",
            user_id=user.id,
        )
        db.session.add(member)
        db.session.commit()

        flash(
            f"Admission successful! Member ID: {member_code} | "
            f"Username: {user.username} | Password: {member_code}",
            "success",
        )
        return redirect(url_for("admissions.index"))

    return render_template("admissions/new.html", form={}, today=date.today())


@admissions_bp.route("/admissions/renew/<int:member_id>", methods=["GET", "POST"])
@login_required
@admin_required
def renew(member_id):
    member = Member.query.get_or_404(member_id)
    if request.method == "POST":
        duration_months = int(request.form.get("duration_months", 1))
        # Extend from today if expired, or from current end_date if still active
        base_date = member.membership_end_date or date.today()
        if base_date < date.today():
            base_date = date.today()
        member.membership_end_date = base_date + relativedelta(months=duration_months)
        member.membership_status = "Active"
        db.session.commit()
        flash(f"Membership renewed until {member.membership_end_date}.", "success")
        return redirect(url_for("admissions.index"))
    return render_template("admissions/renew.html", member=member, today=date.today())
