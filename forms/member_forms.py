from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, DateField, SubmitField, PasswordField, SelectField
from wtforms.validators import DataRequired, Length, Email, Optional, EqualTo

class ProfileForm(FlaskForm):
    full_name = StringField("Full Name", validators=[DataRequired(), Length(max=120)])
    phone = StringField("Phone", validators=[DataRequired(), Length(max=30)])
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=120)])
    address = TextAreaField("Address", validators=[DataRequired(), Length(max=255)])
    submit = SubmitField("Update Profile")

class BookingRequestForm(FlaskForm):
    seat_id = SelectField("Seat", coerce=int, validators=[DataRequired()])
    start_date = DateField("Start Date", validators=[DataRequired()])
    end_date = DateField("End Date", validators=[DataRequired()])
    submit = SubmitField("Reserve Seat")

class ChangePasswordForm(FlaskForm):
    old_password = PasswordField("Old Password", validators=[Optional()])
    new_password = PasswordField("New Password", validators=[DataRequired(), Length(min=6, max=128)])
    confirm_password = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("new_password")])
    submit = SubmitField("Change Password")
