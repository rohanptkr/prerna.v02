from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from application import db
from models import DailySeatBooking, Member
from models.attendance import Attendance

SEAT_COLUMNS = {
    1: list(range(19, 0, -1)),
    2: list(range(20, 38)),
    3: list(range(55, 37, -1)),
    4: list(range(56, 74)),
}
TOTAL_COLUMNS = len(SEAT_COLUMNS)
VALID_SEAT_NUMBERS = {seat_number for seats in SEAT_COLUMNS.values() for seat_number in seats}
TOTAL_SEATS = len(VALID_SEAT_NUMBERS)

BOYS_COLUMNS = (1, 2)
GIRLS_COLUMNS = (3, 4)
IST = ZoneInfo("Asia/Kolkata")


def ist_today():
    return datetime.now(IST).date()


def seat_column(seat_number):
    for column_number, seat_numbers in SEAT_COLUMNS.items():
        if seat_number in seat_numbers:
            return column_number
    return None


def seat_section(seat_number):
    column_number = seat_column(seat_number)
    return "Boys" if column_number in BOYS_COLUMNS else "Girls"


def get_bookable_members():
    """Return Active and Expired members available to be assigned a seat."""
    return (
        Member.query.filter(Member.membership_status.in_(["Active", "Expired"]))
        .order_by(Member.full_name)
        .all()
    )


def build_seat_layout(booking_date=None):
    booking_date = booking_date or ist_today()
    todays_bookings = DailySeatBooking.query.filter_by(booking_date=booking_date).all()
    booked_by_seat = {b.seat_number: b for b in todays_bookings}

    columns = {col: [] for col in range(1, TOTAL_COLUMNS + 1)}
    for column_number, seat_numbers in SEAT_COLUMNS.items():
        for seat_number in seat_numbers:
            booking = booked_by_seat.get(seat_number)
            columns[column_number].append(
                {
                    "seat_number": seat_number,
                    "section": seat_section(seat_number),
                    "status": "Booked" if booking else "Available",
                    "member_name": booking.member_name if booking else None,
                    "member_id": booking.member_id if booking else None,
                    "booking_id": booking.id if booking else None,
                }
            )
    return columns


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


def book_seat_for_today(seat_number, member_id, booked_by_user_id=None, booked_by_email=None):
    """Book a seat for today and mark attendance login. Returns (booking, error)."""
    if seat_number not in VALID_SEAT_NUMBERS:
        return None, "Seat number is not part of the configured layout."

    member = Member.query.get(member_id)
    if not member:
        return None, "Member not found."
    if member.membership_status not in ("Active", "Expired"):
        return None, "Only Active or Expired members can be assigned a seat."

    today = ist_today()
    existing = DailySeatBooking.query.filter_by(seat_number=seat_number, booking_date=today).first()
    if existing:
        return None, f"Seat {seat_number} is already booked today by {existing.member_name}."

    # Prevent same member booking two seats today
    member_existing = DailySeatBooking.query.filter_by(member_id=member_id, booking_date=today).first()
    if member_existing:
        return None, f"{member.full_name} already has seat {member_existing.seat_number} today."

    booking = DailySeatBooking(
        seat_number=seat_number,
        member_id=member_id,
        member_name=member.full_name,
        booking_date=today,
        booked_by_user_id=booked_by_user_id,
    )
    db.session.add(booking)
    mark_attendance_login(member_id, seat_label=f"Seat {seat_number}", booked_by_email=booked_by_email)
    db.session.commit()
    return booking, None


def unbook_seat_for_today(seat_number):
    """Unbook a seat for today and mark attendance logout. Returns (success, error)."""
    today = ist_today()
    existing = DailySeatBooking.query.filter_by(seat_number=seat_number, booking_date=today).first()
    if not existing:
        return False, f"Seat {seat_number} is not currently booked today."

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
                seat_label=f"Seat {booking.seat_number}",
                logout_time=None,
            )
            .order_by(Attendance.login_time.desc(), Attendance.id.desc())
            .first()
        )
        if record and record.logout_time is None:
            record.logout_time = datetime.combine(booking.booking_date, time(23, 59, 59))

    DailySeatBooking.query.filter(DailySeatBooking.booking_date < today).delete()
    db.session.commit()
