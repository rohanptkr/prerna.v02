from datetime import date
from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required

from application import db
from models import Booking, Member, Seat
from services.booking_service import enforce_booking_rules, refresh_seat_availability

api_bp = Blueprint("api", __name__, url_prefix="/api")


def admin_api_required(func):
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role.role_name != "Admin":
            return abort(403, description="Admin access required")
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


def member_or_admin(func):
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return abort(401, description="Login required")
        return func(*args, **kwargs)

    wrapper.__name__ = func.__name__
    return wrapper


def member_to_dict(member):
    return {
        "id": member.id,
        "member_code": member.member_code,
        "full_name": member.full_name,
        "phone": member.phone,
        "email": member.email,
        "address": member.address,
        "registration_date": member.registration_date.isoformat() if member.registration_date else None,
        "membership_start_date": member.membership_start_date.isoformat() if member.membership_start_date else None,
        "membership_end_date": member.membership_end_date.isoformat() if member.membership_end_date else None,
        "membership_status": member.membership_status,
        "user_id": member.user_id,
    }


def seat_to_dict(seat):
    return {
        "id": seat.id,
        "seat_number": seat.seat_number,
        "seat_type": seat.seat_type,
        "status": seat.status,
        "monthly_fee": float(seat.monthly_fee),
        "floor": seat.floor,
        "remarks": seat.remarks,
    }


def booking_to_dict(booking):
    return {
        "id": booking.id,
        "member_id": booking.member_id,
        "member_name": booking.member.full_name,
        "seat_id": booking.seat_id,
        "seat_number": booking.seat.seat_number,
        "start_date": booking.start_date.isoformat(),
        "end_date": booking.end_date.isoformat(),
        "booking_status": booking.booking_status,
        "created_at": booking.created_at.isoformat() if booking.created_at else None,
    }


@api_bp.route("/members", methods=["GET"])
@login_required
@admin_api_required
def list_members():
    search = request.args.get("q", "")
    members = Member.query
    if search:
        members = members.filter(Member.full_name.ilike(f"%{search}%") | Member.email.ilike(f"%{search}%"))
    return jsonify([member_to_dict(m) for m in members.order_by(Member.id.desc()).all()])


@api_bp.route("/members/<int:member_id>", methods=["GET"])
@login_required
@admin_api_required
def get_member(member_id):
    member = Member.query.get_or_404(member_id)
    return jsonify(member_to_dict(member))


@api_bp.route("/members", methods=["POST"])
@login_required
@admin_api_required
def create_member():
    data = request.get_json() or {}
    required = ["full_name", "phone", "email", "address", "membership_status"]
    if not all(data.get(field) for field in required):
        return abort(400, description="Missing required member fields")
    member = Member(
        member_code=data.get("member_code") or f"MBR{Member.query.count()+1:04}",
        full_name=data["full_name"],
        phone=data["phone"],
        email=data["email"].lower(),
        address=data["address"],
        membership_start_date=data.get("membership_start_date"),
        membership_end_date=data.get("membership_end_date"),
        membership_status=data["membership_status"],
        user_id=current_user.id,
    )
    db.session.add(member)
    db.session.commit()
    return jsonify(member_to_dict(member)), 201


@api_bp.route("/members/<int:member_id>", methods=["PUT"])
@login_required
@admin_api_required
def update_member(member_id):
    member = Member.query.get_or_404(member_id)
    data = request.get_json() or {}
    for field in ["full_name", "phone", "email", "address", "membership_status"]:
        if field in data:
            setattr(member, field, data[field].lower() if field == "email" else data[field])
    if data.get("membership_start_date"):
        member.membership_start_date = data["membership_start_date"]
    if data.get("membership_end_date"):
        member.membership_end_date = data["membership_end_date"]
    db.session.commit()
    return jsonify(member_to_dict(member))


@api_bp.route("/members/<int:member_id>", methods=["DELETE"])
@login_required
@admin_api_required
def delete_member(member_id):
    member = Member.query.get_or_404(member_id)
    db.session.delete(member)
    db.session.commit()
    return jsonify({"message": "Member deleted"})


@api_bp.route("/seats", methods=["GET"])
@login_required
@admin_api_required
def list_seats():
    refresh_seat_availability()
    search = request.args.get("q", "")
    seats = Seat.query
    if search:
        seats = seats.filter(Seat.seat_number.ilike(f"%{search}%") | Seat.seat_type.ilike(f"%{search}%"))
    return jsonify([seat_to_dict(s) for s in seats.order_by(Seat.id.desc()).all()])


@api_bp.route("/seats/<int:seat_id>", methods=["GET"])
@login_required
@admin_api_required
def get_seat(seat_id):
    seat = Seat.query.get_or_404(seat_id)
    return jsonify(seat_to_dict(seat))


@api_bp.route("/seats", methods=["POST"])
@login_required
@admin_api_required
def create_seat():
    data = request.get_json() or {}
    required = ["seat_number", "seat_type", "status", "monthly_fee", "floor"]
    if not all(data.get(field) for field in required):
        return abort(400, description="Missing required seat fields")
    seat = Seat(
        seat_number=data["seat_number"],
        seat_type=data["seat_type"],
        status=data["status"],
        monthly_fee=data["monthly_fee"],
        floor=data["floor"],
        remarks=data.get("remarks"),
    )
    db.session.add(seat)
    db.session.commit()
    return jsonify(seat_to_dict(seat)), 201


@api_bp.route("/seats/<int:seat_id>", methods=["PUT"])
@login_required
@admin_api_required
def update_seat(seat_id):
    seat = Seat.query.get_or_404(seat_id)
    data = request.get_json() or {}
    for field in ["seat_number", "seat_type", "status", "monthly_fee", "floor", "remarks"]:
        if field in data:
            setattr(seat, field, data[field])
    db.session.commit()
    return jsonify(seat_to_dict(seat))


@api_bp.route("/seats/<int:seat_id>", methods=["DELETE"])
@login_required
@admin_api_required
def delete_seat(seat_id):
    seat = Seat.query.get_or_404(seat_id)
    db.session.delete(seat)
    db.session.commit()
    return jsonify({"message": "Seat deleted"})


@api_bp.route("/bookings", methods=["POST"])
@login_required
@member_or_admin
def book_seat_api():
    data = request.get_json() or {}
    if current_user.role.role_name == "Member":
        member = current_user.member
        if not member:
            return abort(400, description="Member profile required")
        member_id = member.id
    else:
        member_id = data.get("member_id")
        if not member_id:
            return abort(400, description="Member ID required for admin booking")
    seat_id = data.get("seat_id")
    start_date = data.get("start_date")
    end_date = data.get("end_date")
    if not seat_id or not start_date or not end_date:
        return abort(400, description="Missing booking data")
    validation_error = enforce_booking_rules(member_id, seat_id, start_date, end_date)
    if validation_error:
        return abort(400, description=validation_error)
    seat = Seat.query.get_or_404(seat_id)
    booking = Booking(
        member_id=member_id,
        seat_id=seat_id,
        start_date=start_date,
        end_date=end_date,
        booking_status="Confirmed",
    )
    seat.status = "Occupied"
    db.session.add(booking)
    db.session.commit()
    return jsonify(booking_to_dict(booking)), 201
