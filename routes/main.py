from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from services.access_control import first_allowed_endpoint
from services.dashboard_service import calculate_dashboard_metrics

main_bp = Blueprint("main", __name__, template_folder="../templates")
@main_bp.route("/")
@login_required
def index():
    metrics = calculate_dashboard_metrics()
    if current_user.is_member:
        return render_template("dashboard/member_dashboard.html", metrics=metrics)
    if current_user.has_privilege("dashboard.view"):
        return render_template("dashboard/admin_dashboard.html", metrics=metrics)

    fallback_endpoint = first_allowed_endpoint(current_user)
    if fallback_endpoint and fallback_endpoint != "main.index":
        flash("Dashboard access is not assigned to this role.", "warning")
        return redirect(url_for(fallback_endpoint))

    flash("No sidebar access is assigned to this role.", "warning")
    return redirect(url_for("auth.logout"))
