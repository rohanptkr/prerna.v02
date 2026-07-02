from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DecimalField, SelectField, DateField, SubmitField, PasswordField, SelectMultipleField
from wtforms.validators import DataRequired, Length, Optional, NumberRange, Email, EqualTo

class RoleForm(FlaskForm):
    PRIVILEGE_CHOICES = [
        ("dashboard.view", "Dashboard: View"),
        ("admissions.manage", "Admissions: Manage"),
        ("members.manage", "Members: Manage"),
        ("seats.manage", "Seats: Manage"),
        ("bookings.manage", "Bookings: Manage"),
        ("payments.manage", "Payments: Manage"),
        ("reports.view", "Reports: View"),
        ("attendance.view", "Attendance: View"),
        ("users.manage", "Users: Manage"),
        ("roles.manage", "Roles: Manage"),
    ]

    role_name = StringField("Role Name", validators=[DataRequired(), Length(max=64)])
    description = TextAreaField("Description", validators=[Optional(), Length(max=255)])
    privileges = SelectMultipleField("Privileges", choices=PRIVILEGE_CHOICES, validators=[Optional()])
    submit = SubmitField("Save Role")

class UserForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=64)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6, max=128)])
    password2 = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("password")])
    role_id = SelectField("Role", coerce=int, validators=[DataRequired()])
    submit = SubmitField("Save User")


class UserEditForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(max=64)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    password = PasswordField("New Password", validators=[Optional(), Length(min=6, max=128)])
    password2 = PasswordField("Confirm New Password", validators=[Optional(), EqualTo("password")])
    role_id = SelectField("Role", coerce=int, validators=[DataRequired()])
    is_active = SelectField("Active", choices=[("true", "Yes"), ("false", "No")], validators=[DataRequired()])
    submit = SubmitField("Update User")

class MemberForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=120)])
    phone = StringField("Phone", validators=[DataRequired(), Length(max=30)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    address = TextAreaField("Address", validators=[DataRequired(), Length(max=255)])
    membership_start_date = DateField("Membership Start", validators=[Optional()])
    membership_end_date = DateField("Membership End", validators=[Optional()])
    membership_status = SelectField("Membership Status", choices=[("Active", "Active"), ("Expired", "Expired"), ("Pending", "Pending")], validators=[DataRequired()])
    submit = SubmitField("Save Member")

class SeatForm(FlaskForm):
    seat_number = StringField("Seat Number", validators=[DataRequired(), Length(max=32)])
    seat_type = StringField("Seat Type", validators=[DataRequired(), Length(max=64)])
    status = SelectField("Status", choices=[("Available", "Available"), ("Occupied", "Occupied"), ("Unavailable", "Unavailable")], validators=[DataRequired()])
    monthly_fee = DecimalField("Monthly Fee", validators=[DataRequired(), NumberRange(min=0)], places=2)
    floor = StringField("Floor", validators=[DataRequired(), Length(max=32)])
    remarks = TextAreaField("Remarks", validators=[Optional(), Length(max=255)])
    submit = SubmitField("Save Seat")

class BookingForm(FlaskForm):
    member_id = SelectField("Member", coerce=int, validators=[DataRequired()])
    seat_id = SelectField("Seat", coerce=int, validators=[DataRequired()])
    start_date = DateField("Start Date", validators=[DataRequired()])
    end_date = DateField("End Date", validators=[DataRequired()])
    submit = SubmitField("Create Booking")

class PaymentForm(FlaskForm):
    member_id = SelectField("Member", coerce=int, validators=[DataRequired()])
    booking_id = SelectField("Booking", coerce=int, validators=[DataRequired()])
    amount = DecimalField("Amount", validators=[DataRequired(), NumberRange(min=0)], places=2)
    payment_method = SelectField("Payment Method", choices=[("Credit Card", "Credit Card"), ("Bank Transfer", "Bank Transfer"), ("Cash", "Cash")], validators=[DataRequired()])
    payment_status = SelectField("Payment Status", choices=[("Completed", "Completed"), ("Pending", "Pending"), ("Failed", "Failed")], validators=[DataRequired()])
    transaction_reference = StringField("Transaction Reference", validators=[DataRequired(), Length(max=128)])
    submit = SubmitField("Save Payment")
