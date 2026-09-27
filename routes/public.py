from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from flask_login import current_user

public_bp = Blueprint("public", __name__, template_folder="../templates")


@public_bp.route("/home")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    return render_template("public/index.html")


@public_bp.route("/contact", methods=["GET", "POST"])
def contact():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        email = (request.form.get("email") or "").strip()
        subject = (request.form.get("subject") or "").strip()
        message = (request.form.get("message") or "").strip()

        if not name or not email or not message:
            flash("Please fill Name, Email, and Message fields.", "danger")
            return redirect(url_for("public.contact"))

        # Store incoming contact details in app logs for follow-up.
        current_app.logger.info(
            "Contact inquiry received | name=%s | phone=%s | email=%s | subject=%s | message=%s",
            name,
            phone,
            email,
            subject,
            message,
        )
        flash("Thanks, your message has been received. We will contact you soon.", "success")
        return redirect(url_for("public.contact"))

    return render_template("public/contact.html")
