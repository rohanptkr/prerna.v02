from datetime import date, datetime

from application import db
from models import DailySeatBooking, Member
from models.attendance import Attendance

SEATS_PER_COLUMN = 19
TOTAL_COLUMNS = 4
TOTAL_SEATS = SEATS_PER_COLUMN * TOTAL_COLUMNS  # 76

BOYS_COLUMNS = (1, 2)
GIRLS_COLUMNS = (3, 4)


def seat_column(seat_number):
    return ((seat_number - 1) // SEATS_PER_COLUMN) + 1


def seat_section(seat_number):
    return "Boys" if seat_column(seat_number) in BOYS_COLUMNS else "Girls"


def get_bookable_members():
    """Return Active and Expired members available to be assigned a seat."""
    return (
        Member.query.filter(Member.membership_status.in_(["Active", "Expired"]))
        .order_by(Member.full_name)
        .all()
    )


def build_seat_layout(booking_date=None):
    booking_date = booking_date or date.today()
    todays_bookings = DailySeatBooking.query.filter_by(booking_date=booking_date).all()
    booked_by_seat = {b.seat_number: b for b in todays_bookings}

    columns = {col: [] for col in range(1, TOTAL_COLUMNS + 1)}
    for seat_number in range(1, TOTAL_SEATS + 1):
        column = seat_column(seat_number)
        booking = booked_by_seat.get(seat_number)
        columns[column].append(
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


def _mark_login(member_id):
    """Create or update today's attendance row with current login time."""
    today = date.today()
    now = datetime.utcnow()
    record = Attendance.query.filter_by(member_id=member_id, attendance_date=today).first()
    if record:
        record.login_time = now
        record.logout_time = None  # reset logout if they re-enter
    else:
        record = Attendance(
            member_id=member_id,
            attendance_date=today,
            login_time=now,
        )
        db.session.add(record)
    db.session.flush()


def _mark_logout(member_id):
    """Set logout time on today's attendance row."""
    today = date.today()
    now = datetime.utcnow()
    record = Attendance.query.filter_by(member_id=member_id, attendance_date=today).first()
    if record:
        record.logout_time = now
    db.session.flush()


def book_seat_for_today(seat_number, member_id, booked_by_user_id=None):
    """Book a seat for today and mark attendance login. Returns (booking, error)."""
    if not (1 <= seat_number <= TOTAL_SEATS):
        return None, f"Seat number must be between 1 and {TOTAL_SEATS}."

    member = Member.query.get(member_id)
    if not member:
        return None, "Member not found."
    if member.membership_status not in ("Active", "Expired"):
        return None, "Only Active or Expired members can be assigned a seat."

    today = date.today()
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
    _mark_login(member_id)
    db.session.commit()
    return booking, None


def unbook_seat_for_today(seat_number):
    """Unbook a seat for today and mark attendance logout. Returns (success, error)."""
    today = date.today()
    existing = DailySeatBooking.query.filter_by(seat_number=seat_number, booking_date=today).first()
    if not existing:
        return False, f"Seat {seat_number} is not currently booked today."

    member_id = existing.member_id
    db.session.delete(existing)
    _mark_logout(member_id)
    db.session.commit()
    return True, None


def cleanup_past_bookings():
    today = date.today()
    DailySeatBooking.query.filter(DailySeatBooking.booking_date < today).delete()
    db.session.commit()
