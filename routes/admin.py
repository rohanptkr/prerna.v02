from datetime import date
from functools import wraps
from flask import Blueprint, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user, login_required
from io import StringIO
import csv

from application import db
from forms.admin_forms import MemberForm, PaymentForm, RoleForm, SeatForm, BookingForm, UserForm
from models import Booking, Member, Payment, Role, Seat, User
from models.attendance import Attendance
from services.booking_service import enforce_booking_rules, group_payments_by_month

admin_bp = Blueprint("admin", __name__, template_folder="../templates")


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
@admin_required
def dashboard():
    today = date.today()
    metrics = {
        "active_members": Member.query.filter_by(membership_status="Active").count(),
        "expired_members": Member.query.filter_by(membership_status="Expired").count(),
        "occupied_seats": Seat.query.filter_by(status="Occupied").count(),
        "available_seats": Seat.query.filter_by(status="Available").count(),
        "today_attendance": Attendance.query.filter_by(attendance_date=today).count(),
    }
    return render_template("dashboard/admin_dashboard.html", metrics=metrics)


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
        flash("Booking created successfully.", "success")
        return redirect(url_for("admin.bookings"))
    return render_template("admin/booking_form.html", form=form, action="Add")


@admin_bp.route("/payments")
@login_required
@admin_required
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
@admin_required
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
@admin_required
def reports():
    active_members = Member.query.filter_by(membership_status="Active").count()
    expired_members = Member.query.filter_by(membership_status="Expired").count()
    occupied_seats = Seat.query.filter_by(status="Occupied").count()
    available_seats = Seat.query.filter_by(status="Available").count()
    revenue_summary = db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0)).scalar()
    monthly_collections = group_payments_by_month()
    return render_template(
        "admin/reports.html",
        active_members=active_members,
        expired_members=expired_members,
        occupied_seats=occupied_seats,
        available_seats=available_seats,
        revenue_summary=revenue_summary,
        monthly_collections=monthly_collections,
    )


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
@admin_required
def users():
    page = request.args.get("page", 1, type=int)
    search = request.args.get("q", "")
    query = User.query.join(Role)
    if search:
        query = query.filter(User.username.ilike(f"%{search}%") | User.email.ilike(f"%{search}%") | Role.role_name.ilike(f"%{search}%"))
    pagination = query.order_by(User.created_at.desc()).paginate(page=page, per_page=12)
    return render_template("admin/users.html", pagination=pagination, search=search)


@admin_bp.route("/users/add", methods=["GET", "POST"])
@login_required
@admin_required
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


@admin_bp.route("/roles")
@login_required
@admin_required
def roles():
    roles = Role.query.order_by(Role.role_name).all()
    return render_template("admin/roles.html", roles=roles)


@admin_bp.route("/roles/add", methods=["GET", "POST"])
@login_required
@admin_required
def add_role():
    form = RoleForm()
    if form.validate_on_submit():
        if Role.query.filter_by(role_name=form.role_name.data).first():
            flash("Role already exists.", "warning")
            return render_template("admin/role_form.html", form=form, action="Add")
        role = Role(role_name=form.role_name.data, description=form.description.data)
        db.session.add(role)
        db.session.commit()
        flash("Role created successfully.", "success")
        return redirect(url_for("admin.roles"))
    return render_template("admin/role_form.html", form=form, action="Add")


@admin_bp.route("/export/payments")
@login_required
@admin_required
def export_payments():
    rows = [
        (p.transaction_reference, p.member.full_name, p.booking.id, p.amount, p.payment_method, p.payment_date, p.payment_status)
        for p in Payment.query.order_by(Payment.id).all()
    ]
    return csv_response("payments.csv", rows, ["Transaction", "Member", "Booking ID", "Amount", "Method", "Date", "Status"])
