from datetime import date
from functools import wraps
from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from io import StringIO
import csv
from sqlalchemy.exc import IntegrityError

from application import db
from forms.admin_forms import MemberForm, PaymentForm, RoleForm, SeatForm, BookingForm, UserForm, UserEditForm
from models import AuditLog, Booking, DailySeatBooking, Member, Payment, Role, Seat, User
from services.access_control import privilege_required
from services.booking_service import enforce_booking_rules, group_payments_by_month
from services.dashboard_service import (
    calculate_dashboard_metrics,
    get_dashboard_attendance_entries,
    get_dashboard_member_list,
)
from services.daily_seat_service import build_booking_source_label, get_client_ip, mark_attendance_login

admin_bp = Blueprint("admin", __name__, template_folder="../templates")


def _latest_seat_by_member(member_ids):
    seat_by_member = {}
    if not member_ids:
        return seat_by_member

    bookings = (
        Booking.query.join(Seat)
        .filter(
            Booking.member_id.in_(member_ids),
            Booking.booking_status == "Confirmed",
        )
        .order_by(Booking.end_date.desc(), Booking.id.desc())
        .all()
    )

    for booking in bookings:
        if booking.member_id in seat_by_member:
            continue
        seat_by_member[booking.member_id] = booking.seat.seat_number if booking.seat else "-"

    return seat_by_member


def admin_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role.role_name != "Admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)

    return wrapper


@admin_bp.route("/dashboard")
@login_required
@privilege_required("dashboard.view", message="Dashboard access is not assigned to this role.")
def dashboard():
    metrics = calculate_dashboard_metrics()
    return render_template("dashboard/admin_dashboard.html", metrics=metrics)


@admin_bp.route("/dashboard/member-list")
@login_required
@privilege_required("dashboard.view", message="Dashboard access is not assigned to this role.")
def dashboard_member_list():
    category = request.args.get("category", "").strip()
    lab = request.args.get("lab", "").strip() or None

    valid_categories = {
        "attendance": "Today's Total Attendance",
        "active": "Active Members",
        "expired": "Expired Members",
        "expiring_soon": "Admissions Expiring Soon",
        "new_admissions": "New Admissions (Last 7 Days)",
    }
    if category not in valid_categories:
        flash("Invalid dashboard list selection.", "danger")
        return redirect(url_for("admin.dashboard"))

    if lab not in {None, "Lab 1", "Lab 2"}:
        flash("Invalid lab filter.", "danger")
        return redirect(url_for("admin.dashboard"))

    attendance_entries = []
    members = []
    member_seat_by_id = {}
    if category == "attendance":
        attendance_entries = get_dashboard_attendance_entries(lab=lab)
    else:
        members = get_dashboard_member_list(category, lab=lab)
        if category in {"active", "expired", "expiring_soon", "new_admissions"}:
            member_seat_by_id = _latest_seat_by_member([member.id for member in members])

    heading = valid_categories[category]
    if lab:
        heading = f"{lab} {heading}"

    return render_template(
        "dashboard/member_names.html",
        heading=heading,
        members=members,
        attendance_entries=attendance_entries,
        show_seat=(category in {"attendance", "active", "expired", "expiring_soon", "new_admissions"}),
        member_seat_by_id=member_seat_by_id,
        lab=lab,
        category=category,
        today=date.today(),
    )


@admin_bp.route("/members")
@login_required
@admin_required
def members():
    search = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    query = Member.query
    if search:
        query = query.filter(Member.full_name.ilike(f"%{search}%"))
    pagination = query.order_by(Member.registration_date.desc()).paginate(page=page, per_page=12)
    return render_template("admin/members.html", pagination=pagination, search=search)


@admin_bp.route("/members/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_member():
    form = MemberForm()
    if form.validate_on_submit():
        member = Member(
            member_code=f"MBR{Member.query.count()+1:04}",
            full_name=form.full_name.data,
            phone=form.phone.data,
            email=form.email.data.lower(),
            address=form.address.data,
            membership_start_date=form.membership_start_date.data,
            membership_end_date=form.membership_end_date.data,
            membership_status=form.membership_status.data,
            user_id=current_user.id,
        )
        db.session.add(member)
        db.session.commit()
        flash("Member added successfully.", "success")
        return redirect(url_for("admin.members"))
    return render_template("admin/member_form.html", form=form, action="Add")


@admin_bp.route("/seats")
@login_required
@admin_required
def seats():
    search = request.args.get("q", "")
    page = request.args.get("page", 1, type=int)
    query = Seat.query
    if search:
        query = query.filter(Seat.seat_number.ilike(f"%{search}%"))
    pagination = query.order_by(Seat.seat_number).paginate(page=page, per_page=12)
    return render_template("admin/seats.html", pagination=pagination, search=search)


@admin_bp.route("/seats/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_seat():
    form = SeatForm()
    if form.validate_on_submit():
        seat = Seat(
            seat_number=form.seat_number.data,
            seat_type=form.seat_type.data,
            status=form.status.data,
            monthly_fee=form.monthly_fee.data,
            floor=form.floor.data,
            remarks=form.remarks.data,
        )
        db.session.add(seat)
        db.session.commit()
        flash("Seat created successfully.", "success")
        return redirect(url_for("admin.seats"))
    return render_template("admin/seat_form.html", form=form, action="Add")


@admin_bp.route("/bookings")
@login_required
@admin_required
def bookings():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    query = Booking.query.join(Member).join(Seat)
    if search:
        query = query.filter(
            Member.full_name.ilike(f"%{search}%") | Seat.seat_number.ilike(f"%{search}%")
        )
    pagination = query.order_by(Booking.created_at.desc()).paginate(page=page, per_page=12)
    return render_template("admin/bookings.html", pagination=pagination, search=search)


@admin_bp.route("/bookings/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_booking():
    form = BookingForm()
    form.member_id.choices = [(m.id, m.full_name) for m in Member.query.order_by(Member.full_name).all()]
    form.seat_id.choices = [(s.id, s.seat_number) for s in Seat.query.filter_by(status="Available").order_by(Seat.seat_number).all()]
    if form.validate_on_submit():
        member = Member.query.get(form.member_id.data)
        seat = Seat.query.get(form.seat_id.data)
        validation_error = enforce_booking_rules(member.id, seat.id, form.start_date.data, form.end_date.data)
        if validation_error:
            flash(validation_error, "warning")
            return render_template("admin/booking_form.html", form=form, action="Add")
        booking = Booking(
            member_id=form.member_id.data,
            seat_id=form.seat_id.data,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            booking_status="Confirmed",
        )
        seat.status = "Occupied"
        db.session.add(booking)
        db.session.commit()
        if form.start_date.data <= date.today() <= form.end_date.data:
            mark_attendance_login(
                member.id,
                seat_label=seat.seat_number,
                booked_by_email=build_booking_source_label(
                    actor_label=current_user.email,
                    client_ip=get_client_ip(request.headers, request.remote_addr),
                ),
            )
            db.session.commit()
        flash("Booking created successfully.", "success")
        return redirect(url_for("admin.bookings"))
    return render_template("admin/booking_form.html", form=form, action="Add")


@admin_bp.route("/payments")
@login_required
@privilege_required("payments.manage", message="Payments access is not assigned to this role.")
def payments():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    query = Payment.query.join(Member)
    if search:
        query = query.filter(Member.full_name.ilike(f"%{search}%"))
    pagination = query.order_by(Payment.payment_date.desc()).paginate(page=page, per_page=12)
    return render_template("admin/payments.html", pagination=pagination, search=search)


@admin_bp.route("/payments/add", methods=["GET", "POST"])
@login_required
@privilege_required("payments.manage", message="Payments access is not assigned to this role.")
def add_payment():
    form = PaymentForm()
    form.member_id.choices = [(m.id, m.full_name) for m in Member.query.order_by(Member.full_name).all()]
    form.booking_id.choices = [(b.id, f"{b.id} - {b.seat.seat_number}") for b in Booking.query.order_by(Booking.created_at.desc()).all()]
    if form.validate_on_submit():
        payment = Payment(
            member_id=form.member_id.data,
            booking_id=form.booking_id.data,
            amount=form.amount.data,
            payment_method=form.payment_method.data,
            payment_status=form.payment_status.data,
            transaction_reference=form.transaction_reference.data,
        )
        db.session.add(payment)
        db.session.commit()
        flash("Payment recorded successfully.", "success")
        return redirect(url_for("admin.payments"))
    return render_template("admin/payment_form.html", form=form, action="Add")


@admin_bp.route("/reports")
@login_required
@privilege_required("reports.view", message="Reports access is not assigned to this role.")
def reports():
    metrics = calculate_dashboard_metrics()
    revenue_summary = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).scalar()
    monthly_collections = group_payments_by_month()
    return render_template(
        "admin/reports.html",
        active_members=metrics["active_members"],
        expired_members=metrics["expired_members"],
        occupied_seats=metrics["occupied_seats"],
        available_seats=metrics["available_seats"],
        revenue_summary=revenue_summary,
        monthly_collections=monthly_collections,
    )


@admin_bp.route("/logs")
@login_required
@admin_required
def audit_logs():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "").strip()
    method = request.args.get("method", "").strip().upper()

    query = AuditLog.query.join(User)
    if search:
        query = query.filter(
            User.username.ilike(f"%{search}%")
            | User.email.ilike(f"%{search}%")
            | AuditLog.endpoint.ilike(f"%{search}%")
            | AuditLog.path.ilike(f"%{search}%")
        )
    if method in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        query = query.filter(AuditLog.method == method)

    pagination = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).paginate(page=page, per_page=25)
    return render_template("admin/audit_logs.html", pagination=pagination, search=search, method=method)


def csv_response(filename, rows, headers):
    csv_file = StringIO()
    writer = csv.writer(csv_file)
    writer.writerow(headers)
    writer.writerows(rows)
    csv_file.seek(0)
    return send_file(
        csv_file,
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


@admin_bp.route("/export/members")
@login_required
@admin_required
def export_members():
    rows = [(m.member_code, m.full_name, m.email, m.phone, m.address, m.membership_status, m.registration_date) for m in Member.query.order_by(Member.id).all()]
    return csv_response("members.csv", rows, ["Member Code", "Full Name", "Email", "Phone", "Address", "Status", "Registered At"])


@admin_bp.route("/export/seats")
@login_required
@admin_required
def export_seats():
    rows = [(s.seat_number, s.seat_type, s.status, s.monthly_fee, s.floor, s.remarks) for s in Seat.query.order_by(Seat.id).all()]
    return csv_response("seats.csv", rows, ["Seat Number", "Type", "Status", "Monthly Fee", "Floor", "Remarks"])


@admin_bp.route("/export/bookings")
@login_required
@admin_required
def export_bookings():
    rows = [
        (b.id, b.member.full_name, b.seat.seat_number, b.start_date, b.end_date, b.booking_status, b.created_at)
        for b in Booking.query.order_by(Booking.id).all()
    ]
    return csv_response("bookings.csv", rows, ["Booking ID", "Member", "Seat", "Start Date", "End Date", "Status", "Created At"])


@admin_bp.route("/users")
@login_required
@privilege_required("users.manage", message="User management access is not assigned to this role.")
def users():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    query = User.query.join(Role)
    if search:
        query = query.filter(User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%") | Role.role_name.ilike(f"%{search}%"))
    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=12)
    return render_template("admin/users.html", pagination=pagination, search=search)


def _get_or_create_archived_member_user():
    archived = User.query.filter_by(email="archived-member@local.invalid").first()
    if archived:
        return archived

    member_role = Role.query.filter_by(role_name="Member").first()
    if not member_role:
        member_role = Role(role_name="Member", description="Library member")
        db.session.add(member_role)
        db.session.flush()

    archived = User(
        username="archived_member_user",
        email="archived-member@local.invalid",
        role_id=member_role.id,
        is_active=False,
        is_locked=True,
    )
    archived.set_password("archived-member")
    db.session.add(archived)
    db.session.flush()
    return archived


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
@privilege_required("users.manage", message="User management access is not assigned to this role.")
def delete_user(user_id):
    user = User.query.get_or_404(user_id)

    if user.id == current_user.id:
        flash("You cannot delete your own account.", "warning")
        return redirect(url_for("admin.users"))

    if user.role and user.role.is_admin:
        admin_count = User.query.join(Role).filter(Role.role_name == "Admin").count()
        if admin_count <= 1:
            flash("Cannot delete the last admin user.", "warning")
            return redirect(url_for("admin.users"))

    linked_members = Member.query.filter_by(user_id=user.id).all()
    if linked_members:
        non_deleted_members = [member for member in linked_members if member.membership_status != "Deleted"]
        if non_deleted_members:
            flash(
                "This user is linked to an active admission record. Delete admission first or disable login from admissions.",
                "warning",
            )
            return redirect(url_for("admin.users"))

        archived_user = _get_or_create_archived_member_user()
        if archived_user.id == user.id:
            flash("Archived user cannot be deleted.", "warning")
            return redirect(url_for("admin.users"))

        for member in linked_members:
            member.user_id = archived_user.id

    # Keep booking history but detach user reference so deletion is possible.
    DailySeatBooking.query.filter_by(booked_by_user_id=user.id).update(
        {DailySeatBooking.booked_by_user_id: None},
        synchronize_session=False,
    )

    try:
        db.session.delete(user)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        flash("User cannot be deleted because related records still exist.", "danger")
        return redirect(url_for("admin.users"))

    flash("User deleted successfully.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/users/add", methods=["GET", "POST"])
@login_required
@privilege_required("users.manage", message="User management access is not assigned to this role.")
def add_user():
    form = UserForm()
    form.role_id.choices = [(r.id, r.role_name) for r in Role.query.order_by(Role.role_name).all()]
    if form.validate_on_submit():
        if User.query.filter((User.username == form.username.data) | (User.email == form.email.data.lower())).first():
            flash("Username or email already exists.", "warning")
            return render_template("admin/user_form.html", form=form, action="Add")
        user = User(username=form.username.data, email=form.email.data.lower(), role_id=form.role_id.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash("User created successfully.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/user_form.html", form=form, action="Add")


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@login_required
@privilege_required("users.manage", message="User management access is not assigned to this role.")
def edit_user(user_id):
    user = User.query.get_or_404(user_id)
    form = UserEditForm()
    form.role_id.choices = [(r.id, r.role_name) for r in Role.query.order_by(Role.role_name).all()]

    if request.method == "GET":
        form.username.data = user.username
        form.email.data = user.email
        form.role_id.data = user.role_id
        form.is_active.data = "true" if user.is_active else "false"

    if form.validate_on_submit():
        existing_username = User.query.filter(User.username == form.username.data, User.id != user.id).first()
        if existing_username:
            flash("Username already exists.", "warning")
            return render_template("admin/user_form.html", form=form, action="Edit")

        existing_email = User.query.filter(User.email == form.email.data.lower(), User.id != user.id).first()
        if existing_email:
            flash("Email already exists.", "warning")
            return render_template("admin/user_form.html", form=form, action="Edit")

        user.username = form.username.data
        user.email = form.email.data.lower()
        user.role_id = form.role_id.data
        user.is_active = form.is_active.data == "true"

        if form.password.data:
            user.set_password(form.password.data)
            if hasattr(user, "failed_login_attempts"):
                user.failed_login_attempts = 0
            if hasattr(user, "is_locked"):
                user.is_locked = False

        db.session.commit()
        flash("User updated successfully.", "success")
        return redirect(url_for("admin.users"))

    return render_template("admin/user_form.html", form=form, action="Edit")


@admin_bp.route("/roles")
@login_required
@privilege_required("roles.manage", message="Role management access is not assigned to this role.")
def roles():
    roles = Role.query.order_by(Role.role_name).all()
    return render_template("admin/roles.html", roles=roles)


@admin_bp.route("/roles/add", methods=["GET", "POST"])
@login_required
@privilege_required("roles.manage", message="Role management access is not assigned to this role.")
def add_role():
    form = RoleForm()
    if form.validate_on_submit():
        if Role.query.filter_by(role_name=form.role_name.data).first():
            flash("Role already exists.", "warning")
            return render_template("admin/role_form.html", form=form, action="Add")
        selected_privileges = sorted(set(form.privileges.data or []))
        role = Role(
            role_name=form.role_name.data,
            description=form.description.data,
            privileges=",".join(selected_privileges),
        )
        db.session.add(role)
        db.session.commit()
        flash("Role created successfully.", "success")
        return redirect(url_for("admin.roles"))
    return render_template("admin/role_form.html", form=form, action="Add")


@admin_bp.route("/roles/<int:role_id>/delete", methods=["POST"])
@login_required
@privilege_required("roles.manage", message="Role management access is not assigned to this role.")
def delete_role(role_id):
    role = Role.query.get_or_404(role_id)

    if User.query.filter_by(role_id=role.id).count():
        flash("Cannot delete a role that is assigned to users. Reassign those users first.", "warning")
        return redirect(url_for("admin.roles"))

    db.session.delete(role)
    db.session.commit()
    flash("Role deleted successfully.", "success")
    return redirect(url_for("admin.roles"))


@admin_bp.route("/export/payments")
@login_required
@privilege_required("payments.manage", message="Payments access is not assigned to this role.")
def export_payments():
    rows = [
        (p.transaction_reference, p.member.full_name, p.booking.id, p.amount, p.payment_method, p.payment_date, p.payment_status)
        for p in Payment.query.order_by(Payment.id).all()
    ]
    return csv_response("payments.csv", rows, ["Transaction", "Member", "Booking ID", "Amount", "Method", "Date", "Status"])
