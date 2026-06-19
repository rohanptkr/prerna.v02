from datetime import date
from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from application import db
from forms.member_forms import BookingRequestForm, ChangePasswordForm, ProfileForm
from models import Booking, Member, Seat, Payment

member_bp = Blueprint("member", __name__, template_folder="../templates")


def member_required(func):
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role.role_name != "Member":
            flash("Member access required.", "danger")
            return redirect(url_for("auth.login"))
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


@member_bp.route("/dashboard")
@login_required
@member_required
def dashboard():
    member = Member.query.filter_by(user_id=current_user.id).first()
    active_bookings = Booking.query.filter_by(member_id=member.id, booking_status="Confirmed").all() if member else []
    return render_template("dashboard/member_dashboard.html", member=member, active_bookings=active_bookings)


@member_bp.route("/profile", methods=["GET", "POST"])
@login_required
@member_required
def profile():
    member = Member.query.filter_by(user_id=current_user.id).first()
    form = ProfileForm(obj=member)
    if form.validate_on_submit():
        member.full_name = form.full_name.data
        member.phone = form.phone.data
        member.email = form.email.data.lower()
        member.address = form.address.data
        db.session.commit()
        flash("Profile updated successfully.", "success")
        return redirect(url_for("member.profile"))
    return render_template("member/profile.html", form=form, member=member)


@member_bp.route("/book", methods=["GET", "POST"])
@login_required
@member_required
def book_seat():
    member = Member.query.filter_by(user_id=current_user.id).first()
    form = BookingRequestForm()
    available_seats = Seat.query.filter_by(status="Available").all()
    if request.method == "GET":
        return render_template("member/book_seat.html", form=form, seats=available_seats)

    if form.validate_on_submit():
        if not member:
            flash("Member profile required before booking.", "warning")
            return redirect(url_for("member.profile"))
        existing = Booking.query.filter(Booking.member_id == member.id, Booking.booking_status == "Confirmed", Booking.end_date >= date.today()).first()
        if existing:
            flash("You already have an active booking.", "warning")
            return redirect(url_for("member.booking_history"))
        seat = Seat.query.filter_by(id=int(form.seat_id.data), status="Available").first()
        if not seat:
            flash("Selected seat is not available.", "danger")
            return redirect(url_for("member.book_seat"))
        new_booking = Booking(
            member_id=member.id,
            seat_id=seat.id,
            start_date=form.start_date.data,
            end_date=form.end_date.data,
            booking_status="Confirmed",
        )
        seat.status = "Occupied"
        db.session.add(new_booking)
        db.session.commit()
        flash("Seat reserved successfully.", "success")
        return redirect(url_for("member.booking_history"))
    return render_template("member/book_seat.html", form=form, seats=available_seats)


@member_bp.route("/history")
@login_required
@member_required
def booking_history():
    member = Member.query.filter_by(user_id=current_user.id).first()
    bookings = Booking.query.filter_by(member_id=member.id).order_by(Booking.created_at.desc()).all() if member else []
    payments = Payment.query.filter_by(member_id=member.id).order_by(Payment.payment_date.desc()).all() if member else []
    return render_template("member/booking_history.html", bookings=bookings, payments=payments)


@member_bp.route("/change-password", methods=["GET", "POST"])
@login_required
@member_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.old_password.data):
            flash("Old password is incorrect.", "danger")
            return redirect(url_for("member.change_password"))
        current_user.set_password(form.new_password.data)
        db.session.commit()
        flash("Password updated successfully.", "success")
        return redirect(url_for("member.dashboard"))
    return render_template("member/change_password.html", form=form)
