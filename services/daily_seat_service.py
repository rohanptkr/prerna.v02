from datetime import date, datetime, time, timedelta
import re
from zoneinfo import ZoneInfo

from application import db
from models import AppSetting, Booking, DailySeatBooking, Member, Seat
from models.attendance import Attendance

LAB_2_COLUMNS = {
    1: [1000 + value for value in range(19, 0, -1)],
    2: [1000 + value for value in range(20, 38)],
    3: [1000 + value for value in range(55, 37, -1)],
    4: [1000 + value for value in range(56, 86)],
}

LAB_1_ROWS = {
    1: list(range(1, 9)),
    2: list(range(9, 17)),
    3: list(range(17, 25)),
    4: list(range(25, 33)),
    5: list(range(33, 41)),
    6: list(range(41, 49)),
    7: list(range(49, 57)),
    8: list(range(57, 65)),
    9: list(range(65, 73)),
    10: list(range(73, 81)),
}

VALID_SEAT_NUMBERS_LAB_2 = {seat_number for seats in LAB_2_COLUMNS.values() for seat_number in seats}
VALID_SEAT_NUMBERS_LAB_1 = {seat_number for seats in LAB_1_ROWS.values() for seat_number in seats}
TOTAL_SEATS_LAB_2 = len(VALID_SEAT_NUMBERS_LAB_2)
TOTAL_SEATS_LAB_1 = len(VALID_SEAT_NUMBERS_LAB_1)

# Backward compatibility for modules still importing TOTAL_SEATS.
TOTAL_SEATS = TOTAL_SEATS_LAB_2

IST = ZoneInfo("Asia/Kolkata")
ALLOW_ALL_BOOKING_SETTING_KEY = "allow_all_member_booking"


def ist_today():
    return datetime.now(IST).date()


def get_lab_seats(lab):
    """Get valid seat numbers for a lab."""
    if lab == 1:
        return VALID_SEAT_NUMBERS_LAB_1
    else:
        return VALID_SEAT_NUMBERS_LAB_2


def infer_lab_from_seat_number(seat_number):
    if seat_number in VALID_SEAT_NUMBERS_LAB_1:
        return 1
    if seat_number in VALID_SEAT_NUMBERS_LAB_2:
        return 2
    return None


def display_seat_number(seat_number, lab):
    if lab == 2:
        return seat_number - 1000
    return seat_number


def seat_label(seat_number, lab):
    prefix = "A" if lab == 1 else "B"
    return f"{prefix}{display_seat_number(seat_number, lab)}"


def seat_label_from_storage(seat_number):
    lab = infer_lab_from_seat_number(seat_number)
    if lab is None:
        return f"Seat {seat_number}"
    return seat_label(seat_number, lab)


def normalize_member_name(member_name):
    return re.sub(r"\s+", " ", str(member_name or "")).strip()


def member_name_key(member_name):
    return normalize_member_name(member_name).casefold()


def get_client_ip(headers=None, remote_addr=None):
    forwarded_for = (headers or {}).get("X-Forwarded-For", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip()
    real_ip = (headers or {}).get("X-Real-IP", "").strip()
    if real_ip:
        return real_ip
    return (remote_addr or "").strip() or None


def build_booking_source_label(actor_label=None, client_ip=None):
    actor_value = str(actor_label or "").strip()
    ip_value = str(client_ip or "").strip()

    if actor_value and ip_value:
        return f"{actor_value} | IP {ip_value}"
    if actor_value:
        return actor_value
    if ip_value:
        return f"IP {ip_value}"
    return None


def storage_seat_number_from_code(seat_code):
    if seat_code is None:
        return None
    code = re.sub(r"[^A-Z0-9]", "", str(seat_code).strip().upper())
    if not code:
        return None
    if code.startswith("A") and code[1:].isdigit():
        return int(code[1:])
    if code.startswith("B") and code[1:].isdigit():
        return 1000 + int(code[1:])
    if code.isdigit():
        return int(code)
    return None


def seat_column_or_row(seat_number, lab):
    """Get the column (lab 2) or row (lab 1) for a seat."""
    if lab == 1:
        for row_number, seat_numbers in LAB_1_ROWS.items():
            if seat_number in seat_numbers:
                return row_number
    else:
        for column_number, seat_numbers in LAB_2_COLUMNS.items():
            if seat_number in seat_numbers:
                return column_number
    return None


def get_bookable_members(expiry_days=15, allow_all=False):
    """Return eligible members for daily booking.

    Default mode: Active + recently expired members.
    Allow-all mode: every non-deleted member.
    """
    if allow_all:
        return (
            Member.query.filter(Member.membership_status != "Deleted")
            .order_by(Member.full_name)
            .all()
        )

    today = ist_today()
    recent_expiry_cutoff = today - timedelta(days=expiry_days)
    return (
        Member.query.filter(
            (Member.membership_status == "Active")
            | (
                (Member.membership_status == "Expired")
                & (Member.membership_end_date.isnot(None))
                & (Member.membership_end_date >= recent_expiry_cutoff)
                & (Member.membership_end_date <= today)
            )
        )
        .order_by(Member.full_name)
        .all()
    )


def is_allow_all_member_booking_enabled():
    setting = AppSetting.query.filter_by(setting_key=ALLOW_ALL_BOOKING_SETTING_KEY).first()
    if not setting:
        return False
    return str(setting.setting_value).strip().lower() in {"1", "true", "yes", "on"}


def set_allow_all_member_booking(enabled):
    setting = AppSetting.query.filter_by(setting_key=ALLOW_ALL_BOOKING_SETTING_KEY).first()
    if not setting:
        setting = AppSetting(
            setting_key=ALLOW_ALL_BOOKING_SETTING_KEY,
            setting_value="true" if enabled else "false",
        )
        db.session.add(setting)
    else:
        setting.setting_value = "true" if enabled else "false"
    db.session.commit()


def is_member_bookable(member, expiry_days=15, allow_all=False):
    if not member:
        return False
    if allow_all:
        return member.membership_status != "Deleted"
    if member.membership_status == "Active":
        return True
    if member.membership_status != "Expired":
        return False
    if not member.membership_end_date:
        return False

    today = ist_today()
    recent_expiry_cutoff = today - timedelta(days=expiry_days)
    return recent_expiry_cutoff <= member.membership_end_date <= today


def build_seat_layout(lab=2, booking_date=None):
    booking_date = booking_date or ist_today()
    todays_bookings = DailySeatBooking.query.filter_by(booking_date=booking_date).all()
    booked_by_seat = {b.seat_number: b for b in todays_bookings}
    booked_member_ids = [booking.member_id for booking in todays_bookings if booking.member_id]
    member_status_by_id = {}
    if booked_member_ids:
        member_status_by_id = {
            member.id: member.membership_status
            for member in Member.query.filter(Member.id.in_(booked_member_ids)).all()
        }

    active_reservations = (
        Booking.query.join(Seat).join(Member)
        .filter(
            Booking.booking_status == "Confirmed",
            Booking.start_date <= booking_date,
            Booking.end_date >= booking_date,
        )
        .all()
    )
    reserved_by_seat = {}
    for reservation in active_reservations:
        if not reservation.seat or not reservation.member:
            continue
        seat_number = storage_seat_number_from_code(reservation.seat.seat_number)
        if seat_number is None:
            continue
        if lab == 1 and seat_number not in VALID_SEAT_NUMBERS_LAB_1:
            continue
        if lab == 2 and seat_number not in VALID_SEAT_NUMBERS_LAB_2:
            continue
        reserved_by_seat[seat_number] = reservation

    if lab == 1:
        layout = {}
        for row_number in sorted(LAB_1_ROWS.keys()):
            layout[row_number] = []
            for seat_number in LAB_1_ROWS[row_number]:
                booking = booked_by_seat.get(seat_number)
                reservation = reserved_by_seat.get(seat_number)
                layout[row_number].append(
                    {
                        "seat_number": seat_number,
                        "seat_label": seat_label(seat_number, 1),
                        "section": None,
                        "status": "Booked" if booking else "Available",
                        "member_name": booking.member_name if booking else (reservation.member.full_name if reservation else None),
                        "member_id": booking.member_id if booking else (reservation.member_id if reservation else None),
                        "member_status": (
                            member_status_by_id.get(booking.member_id)
                            if booking
                            else (reservation.member.membership_status if reservation else None)
                        ),
                        "is_expired_member": (
                            member_status_by_id.get(booking.member_id) == "Expired"
                            if booking
                            else (reservation.member.membership_status == "Expired" if reservation else False)
                        ),
                        "is_reserved": reservation is not None,
                        "booking_id": booking.id if booking else None,
                    }
                )
        return layout
    else:
        layout = {}
        boys_cols = (1, 2)
        girls_cols = (3, 4)
        for column_number, seat_numbers in LAB_2_COLUMNS.items():
            layout[column_number] = []
            for seat_number in seat_numbers:
                booking = booked_by_seat.get(seat_number)
                reservation = reserved_by_seat.get(seat_number)
                section = "Boys" if column_number in boys_cols else "Girls"
                layout[column_number].append(
                    {
                        "seat_number": seat_number,
                        "seat_label": seat_label(seat_number, 2),
                        "section": section,
                        "status": "Booked" if booking else "Available",
                        "member_name": booking.member_name if booking else (reservation.member.full_name if reservation else None),
                        "member_id": booking.member_id if booking else (reservation.member_id if reservation else None),
                        "member_status": (
                            member_status_by_id.get(booking.member_id)
                            if booking
                            else (reservation.member.membership_status if reservation else None)
                        ),
                        "is_expired_member": (
                            member_status_by_id.get(booking.member_id) == "Expired"
                            if booking
                            else (reservation.member.membership_status == "Expired" if reservation else False)
                        ),
                        "is_reserved": reservation is not None,
                        "booking_id": booking.id if booking else None,
                    }
                )
        return layout


def cleanup_old_attendance(days=90):
    """Keep attendance data for the last `days` days only."""
    cutoff_date = ist_today() - timedelta(days=days)
    Attendance.query.filter(Attendance.attendance_date < cutoff_date).delete()
    db.session.flush()


def mark_attendance_login(member_id, seat_label=None, booked_by_email=None):
    """Create today's attendance session row for the member and seat."""
    today = ist_today()
    now = datetime.utcnow()
    cleanup_old_attendance(days=90)
    open_records = (
        Attendance.query.filter_by(member_id=member_id, attendance_date=today, logout_time=None)
        .order_by(Attendance.login_time.desc(), Attendance.id.desc())
        .all()
    )
    for record in open_records:
        record.logout_time = now

    record = Attendance(
        member_id=member_id,
        seat_label=seat_label,
        booked_by_email=booked_by_email,
        attendance_date=today,
        login_time=now,
    )
    db.session.add(record)
    db.session.flush()


def mark_attendance_logout(member_id):
    """Set logout time on the latest open attendance session for today."""
    today = ist_today()
    now = datetime.utcnow()
    record = (
        Attendance.query.filter_by(member_id=member_id, attendance_date=today, logout_time=None)
        .order_by(Attendance.login_time.desc(), Attendance.id.desc())
        .first()
    )
    if record:
        record.logout_time = now
    db.session.flush()


def book_seat_for_today(
    seat_number,
    member_id,
    booked_by_user_id=None,
    booked_by_email=None,
    lab=2,
    allow_all=False,
    expiry_days=15,
):
    """Book a seat for today and mark attendance login. Returns (booking, error)."""
    valid_seats = get_lab_seats(lab)
    if seat_number not in valid_seats:
        return None, "Seat number is not part of the configured layout."

    member = Member.query.get(member_id)
    if not member:
        return None, "Member not found."
    if allow_all:
        if member.membership_status == "Deleted":
            return None, "Deleted members cannot be assigned a seat."
    else:
        if not is_member_bookable(member, expiry_days=expiry_days):
            return None, f"Only Active members or members expired within last {expiry_days} days are allowed."

    today = ist_today()
    seat_label_value = seat_label(seat_number, lab)
    existing = DailySeatBooking.query.filter_by(seat_number=seat_number, booking_date=today).first()
    if existing:
        return None, f"Seat {seat_label_value} is already booked today by {existing.member_name}."

    # Prevent same member booking two seats today
    member_existing = DailySeatBooking.query.filter_by(member_id=member_id, booking_date=today).first()
    if member_existing:
        return None, f"{member.full_name} already has seat {seat_label_from_storage(member_existing.seat_number)} today."

    booking = DailySeatBooking(
        seat_number=seat_number,
        member_id=member_id,
        member_name=member.full_name,
        booking_date=today,
        booked_by_user_id=booked_by_user_id,
    )
    db.session.add(booking)
    mark_attendance_login(member_id, seat_label=seat_label_value, booked_by_email=booked_by_email)
    db.session.commit()
    return booking, None


def toggle_public_seat_for_today(seat_number, member_id, booked_by_email=None, expiry_days=15):
    """Toggle seat state for public QR access using seat number + member.

    Eligibility: Active members or Expired members within `expiry_days` days.
    """
    member = Member.query.get(member_id)
    if not member:
        return None, "Member not found."
    allow_all = is_allow_all_member_booking_enabled()
    if not is_member_bookable(member, expiry_days=expiry_days, allow_all=allow_all):
        if allow_all:
            return None, "Deleted members are not allowed."
        return None, f"Only Active members or members expired within last {expiry_days} days are allowed."

    normalized_name = normalize_member_name(member.full_name)

    lab = infer_lab_from_seat_number(seat_number)
    if lab is None:
        return None, "Seat number is not part of the configured layout."

    today = ist_today()
    seat_label_value = seat_label(seat_number, lab)
    existing = DailySeatBooking.query.filter_by(seat_number=seat_number, booking_date=today).first()

    if existing:
        if existing.member_id != member.id and member_name_key(existing.member_name) != member_name_key(normalized_name):
            return None, (
                f"Seat {seat_label_value} is already booked by {existing.member_name}. "
                "Only that member can unbook this seat."
            )

        db.session.delete(existing)
        if member.id:
            mark_attendance_logout(member.id)
        db.session.commit()
        return {
            "action": "unbooked",
            "seat_number": seat_number,
            "seat_label": seat_label_value,
            "member_name": normalized_name,
            "member_id": member.id,
            "status": "Available",
            "message": f"Seat {seat_label_value} has been unbooked.",
        }, None

    member_existing = DailySeatBooking.query.filter_by(member_id=member.id, booking_date=today).first()
    if member_existing:
        return None, f"{member.full_name} already has seat {seat_label_from_storage(member_existing.seat_number)} today."

    booking = DailySeatBooking(
        seat_number=seat_number,
        member_id=member.id,
        member_name=normalized_name,
        booking_date=today,
        booked_by_user_id=None,
    )
    db.session.add(booking)
    mark_attendance_login(member.id, seat_label=seat_label_value, booked_by_email=booked_by_email)
    db.session.commit()

    return {
        "action": "booked",
        "seat_number": booking.seat_number,
        "seat_label": seat_label_value,
        "member_name": booking.member_name,
        "member_id": member.id,
        "status": "Booked",
        "message": f"Seat {seat_label_value} has been booked for {booking.member_name}.",
    }, None


def unbook_seat_for_today(seat_number):
    """Unbook a seat for today and mark attendance logout. Returns (success, error)."""
    today = ist_today()
    seat_label_value = seat_label_from_storage(seat_number)
    existing = DailySeatBooking.query.filter_by(seat_number=seat_number, booking_date=today).first()
    if not existing:
        return False, f"Seat {seat_label_value} is not currently booked today."

    member_id = existing.member_id
    db.session.delete(existing)
    mark_attendance_logout(member_id)
    db.session.commit()
    return True, None


def cleanup_past_bookings():
    today = ist_today()

    # Auto-close any attendance rows left open from previous dates before removing bookings.
    stale_bookings = DailySeatBooking.query.filter(DailySeatBooking.booking_date < today).all()
    for booking in stale_bookings:
        record = (
            Attendance.query.filter_by(
                member_id=booking.member_id,
                attendance_date=booking.booking_date,
                seat_label=seat_label_from_storage(booking.seat_number),
                logout_time=None,
            )
            .order_by(Attendance.login_time.desc(), Attendance.id.desc())
            .first()
        )
        if record and record.logout_time is None:
            record.logout_time = datetime.combine(booking.booking_date, time(23, 59, 59))

    DailySeatBooking.query.filter(DailySeatBooking.booking_date < today).delete()
    db.session.commit()
