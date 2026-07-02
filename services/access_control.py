from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user


SIDEBAR_PRIVILEGE_ITEMS = [
    ("dashboard.view", "main.index"),
    ("admissions.manage", "admissions.index"),
    ("daily_seats.view", "daily_seats.dashboard"),
    ("attendance.view", "attendance.index"),
    ("attendance.calendar.view", "attendance.calendar_view"),
    ("payments.manage", "admin.payments"),
    ("reports.view", "admin.reports"),
    ("users.manage", "admin.users"),
    ("roles.manage", "admin.roles"),
]


def first_allowed_endpoint(user):
    if not user or not getattr(user, "is_authenticated", False):
        return None

    if user.is_member:
        return "main.index"

    for privilege, endpoint in SIDEBAR_PRIVILEGE_ITEMS:
        if user.has_privilege(privilege):
            return endpoint

    return None


def privilege_required(privilege, message="You do not have access to this section.", api=False):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                if api:
                    return abort(401, description="Login required")
                return redirect(url_for("auth.login"))

            if current_user.has_privilege(privilege):
                return func(*args, **kwargs)

            if api:
                return abort(403, description=message)

            flash(message, "danger")
            fallback_endpoint = first_allowed_endpoint(current_user)
            if fallback_endpoint:
                return redirect(url_for(fallback_endpoint))
            return redirect(url_for("auth.logout"))

        return wrapper

    return decorator