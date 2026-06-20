from flask import Blueprint, render_template
from flask_login import current_user, login_required

from services.dashboard_service import calculate_dashboard_metrics

main_bp = Blueprint("main", __name__, template_folder="../templates")
@main_bp.route("/")
@login_required
def index():
    metrics = calculate_dashboard_metrics()
    if current_user.role.role_name == "Admin":
        return render_template("dashboard/admin_dashboard.html", metrics=metrics)
    return render_template("dashboard/member_dashboard.html", metrics=metrics)
