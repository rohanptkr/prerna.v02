from urllib.parse import quote

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from services.access_control import privilege_required
from services.daily_seat_service import (
    build_booking_source_label,
    book_seat_for_today,
    build_seat_layout,
    cleanup_past_bookings,
    get_bookable_members,
    get_client_ip,
    ist_today,
    seat_label,
    seat_label_from_storage,
    storage_seat_number_from_code,
    toggle_public_seat_for_today,
    unbook_seat_for_today,
)

daily_seats_bp = Blueprint("daily_seats", __name__, template_folder="../templates")


@daily_seats_bp.route("/daily-seats/quick-access")
def quick_access():
    cleanup_past_bookings()
    access_url = request.url_root.rstrip("/") + url_for("daily_seats.quick_access")
    qr_image_url = f"https://api.qrserver.com/v1/create-qr-code/?size=260x260&data={quote(access_url, safe='')}"
    members = get_bookable_members(expiry_days=15)
    return render_template(
        "daily_seats/quick_access.html",
        today=ist_today(),
        qr_image_url=qr_image_url,
        members=members,
    )


@daily_seats_bp.route("/daily-seats/quick-access/toggle", methods=["POST"])
def quick_access_toggle():
    data = request.get_json() or {}
    seat_code = data.get("seat_code")
    member_id = data.get("member_id")

    if not seat_code or member_id is None:
        return jsonify({"success": False, "message": "seat_code and member_id are required."}), 400

    try:
        member_id = int(member_id)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "member_id must be an integer."}), 400

    seat_number = storage_seat_number_from_code(seat_code)
    if seat_number is None:
        return jsonify({"success": False, "message": "Invalid seat number. Use A12, B8, 1008, etc."}), 400

    payload, error = toggle_public_seat_for_today(
        seat_number=seat_number,
        member_id=member_id,
        booked_by_email=build_booking_source_label(
            actor_label="QR access",
            client_ip=get_client_ip(request.headers, request.remote_addr),
        ),
        expiry_days=15,
    )
    if error:
        return jsonify({"success": False, "message": error}), 400

    response = {"success": True}
    response.update(payload)
    return jsonify(response)


@daily_seats_bp.route("/daily-seats")
@login_required
@privilege_required("daily_seats.view", message="Daily seat booking access is not assigned to this role.")
def dashboard():
    cleanup_past_bookings()
    lab = request.args.get("lab", 2, type=int)
    if lab not in (1, 2):
        lab = 2
    allow_all_member_booking = bool(session.get("allow_all_member_booking", False))
    columns = build_seat_layout(lab=lab)
    members = get_bookable_members(allow_all=allow_all_member_booking)
    return render_template(
        "daily_seats/dashboard.html",
        columns=columns,
        members=members,
        today=ist_today(),
        lab=lab,
        allow_all_member_booking=allow_all_member_booking,
    )


@daily_seats_bp.route("/daily-seats/toggle-booking-mode", methods=["POST"])
@login_required
@privilege_required("daily_seats.view", message="Daily seat booking access is not assigned to this role.")
def toggle_booking_mode():
    desired_state = request.form.get("allow_all_member_booking", "false").strip().lower()
    session["allow_all_member_booking"] = desired_state == "true"

    lab = request.form.get("lab", 2)
    try:
        lab = int(lab)
    except (TypeError, ValueError):
        lab = 2
    if lab not in (1, 2):
        lab = 2

    return redirect(url_for("daily_seats.dashboard", lab=lab))


@daily_seats_bp.route("/daily-seats/book", methods=["POST"])
@login_required
@privilege_required("daily_seats.view", message="Daily seat booking access is not assigned to this role.")
def book_seat():
    data = request.get_json() or {}
    seat_number = data.get("seat_number")
    member_id = data.get("member_id")
    lab = data.get("lab", 2)

    if seat_number is None or member_id is None:
        return jsonify({"success": False, "message": "seat_number and member_id are required."}), 400

    try:
        seat_number = int(seat_number)
        member_id = int(member_id)
        lab = int(lab)
    except (TypeError, ValueError):
        return jsonify({"success": False, "message": "Invalid seat_number, member_id, or lab."}), 400

    if lab not in (1, 2):
        lab = 2

    allow_all_member_booking = bool(session.get("allow_all_member_booking", False))

    booking, error = book_seat_for_today(
        seat_number=seat_number,
        member_id=member_id,
        booked_by_user_id=current_user.id,
        booked_by_email=build_booking_source_label(
            actor_label=current_user.email,
            client_ip=get_client_ip(request.headers, request.remote_addr),
        ),
        lab=lab,
        allow_all=allow_all_member_booking,
    )
    if error:
        return jsonify({"success": False, "message": error}), 400

    return jsonify({
        "success": True,
        "seat_number": booking.seat_number,
        "seat_label": seat_label(booking.seat_number, lab),
        "member_name": booking.member_name,
        "member_id": booking.member_id,
        "member_status": booking.member.membership_status if booking.member else None,
        "is_expired_member": bool(booking.member and booking.member.membership_status == "Expired"),
        "status": "Booked",
    }), 201


@daily_seats_bp.route("/daily-seats/unbook", methods=["POST"])
@login_required
@privilege_required("daily_seats.view", message="Daily seat booking access is not assigned to this role.")
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

    return jsonify({
        "success": True,
        "seat_number": seat_number,
        "seat_label": seat_label_from_storage(seat_number),
        "status": "Available",
    })
