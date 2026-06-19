from datetime import date, datetime, timedelta

from application import create_app, db
from models import Booking, Member, Payment, Role, Seat, User


def seed_data():
    app = create_app()
    with app.app_context():
        db.create_all()

        admin_role = Role.query.filter_by(role_name="Admin").first()
        member_role = Role.query.filter_by(role_name="Member").first()
        if not admin_role:
            admin_role = Role(role_name="Admin", description="Administrator role")
            db.session.add(admin_role)
        if not member_role:
            member_role = Role(role_name="Member", description="Library member role")
            db.session.add(member_role)
        db.session.commit()

        if not User.query.filter_by(email="admin@example.com").first():
            admin = User(username="admin", email="admin@example.com", role=admin_role)
            admin.set_password("Admin123!")
            db.session.add(admin)

        if not User.query.filter_by(email="member@example.com").first():
            member_user = User(username="member", email="member@example.com", role=member_role)
            member_user.set_password("Member123!")
            db.session.add(member_user)
            db.session.commit()
            member_profile = Member(
                member_code="MBR0001",
                full_name="John Doe",
                phone="555-0101",
                email="member@example.com",
                address="123 Library Lane",
                registration_date=datetime.utcnow(),
                membership_start_date=date.today(),
                membership_end_date=date.today() + timedelta(days=30),
                membership_status="Active",
                user_id=member_user.id,
            )
            db.session.add(member_profile)

        if Seat.query.count() == 0:
            seats = [
                Seat(seat_number="A-01", seat_type="Standard", status="Available", monthly_fee=120.00, floor="1", remarks="Quiet zone"),
                Seat(seat_number="A-02", seat_type="Standard", status="Available", monthly_fee=120.00, floor="1", remarks="Window seat"),
                Seat(seat_number="B-01", seat_type="Premium", status="Available", monthly_fee=180.00, floor="2", remarks="Near power outlets"),
            ]
            db.session.add_all(seats)

        db.session.commit()

        member_profile = Member.query.filter_by(email="member@example.com").first()
        seat = Seat.query.filter_by(seat_number="A-01").first()
        if member_profile and seat and not Booking.query.filter_by(member_id=member_profile.id, seat_id=seat.id).first():
            booking = Booking(
                member_id=member_profile.id,
                seat_id=seat.id,
                start_date=date.today(),
                end_date=date.today() + timedelta(days=7),
                booking_status="Confirmed",
            )
            seat.status = "Occupied"
            db.session.add(booking)
            db.session.commit()
            payment = Payment(
                member_id=member_profile.id,
                booking_id=booking.id,
                amount=120.00,
                payment_method="Credit Card",
                payment_status="Completed",
                transaction_reference="TXN0001",
            )
            db.session.add(payment)
            db.session.commit()

        print("Sample data seeded successfully.")


if __name__ == "__main__":
    seed_data()
