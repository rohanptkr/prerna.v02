from datetime import date

from flask import Blueprint, abort, jsonify, render_template, request
from flask_login import current_user, login_required

from services.daily_seat_service import (
    book_seat_for_today,
    build_seat_layout,
    cleanup_past_bookings,
    get_bookable_members,
    unbook_seat_for_today,
)

daily_seats_bp = Blueprint("daily_seats", __name__, template_folder="../templates")


@daily_seats_bp.route("/daily-seats")
@login_required
def dashboard():
    cleanup_past_bookings()
    columns = build_seat_layout()
    members = get_bookable_members()
    return render_template(
        "daily_seats/dashboard.html",
        columns=columns,
        members=members,
        today=date.today(),
    )


@daily_seats_bp.route("/daily-seats/book", methods=["POST"])
@login_required
def book_seat():
    data = request.get_json() or {}
    seat_number = data.get("seat_number")
    member_id = data.get("member_id")

    if seat_number is None or member_id is None:
        return jsonify({"success": False, "message": "seat_number and member_id are required."}), 400

    try:
        seat_number = int(seat_number)
        member_id = int(member_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid seat_number or member_id."}), 400

    booking, error = book_seat_for_today(
        seat_number=seat_number,
        member_id=member_id,
        booked_by_user_id=current_user.id,
    )
    if error:
        return jsonify({"success": False, "message": error}), 400

    return jsonify({
        "success": True,
        "seat_number": booking.seat_number,
        "member_name": booking.member_name,
        "member_id": booking.member_id,
        "status": "Booked",
    }), 201


@daily_seats_bp.route("/daily-seats/unbook", methods=["POST"])
@login_required
def unbook_seat():
    data = request.get_json() or {}
    seat_number = data.get("seat_number")

    if seat_number is None:
        return jsonify({"success": False, "message": "seat_number is required."}), 400

    try:
        seat_number = int(seat_number)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "seat_number must be an integer."}), 400

    success, error = unbook_seat_for_today(seat_number)
    if not success:
        return jsonify({"success": False, "message": error}), 400

    return jsonify({"success": True, "seat_number": seat_number, "status": "Available"})
