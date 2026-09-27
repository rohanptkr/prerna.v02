from flask import Blueprint, redirect, render_template, url_for
from flask_login import current_user

public_bp = Blueprint("public", __name__, template_folder="../templates")


@public_bp.route("/home")
def home():
    if current_user.is_authenticated:
        return redirect(url_for("main.index"))
    return render_template("public/index.html")


@public_bp.route("/contact")
def contact():
    return render_template("public/contact.html")
