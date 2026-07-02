"""Application-level routes: auth, dashboard, uploads, index."""
import os

import pandas as pd
from fastapi import APIRouter, Request

from app.base.utils.config import CSV_EMPLOYEES, CURRENT_FY, DUMMY_USERS, UPLOAD_FOLDER
from app.base.utils.flask_compat import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    send_from_directory,
    session,
    url_for,
    request,
)

pages_bp = Blueprint("pages", __name__, url_prefix="")


@pages_bp.route("/", methods=["GET"], endpoint="index")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("auth.login"))


@pages_bp.route("/login", methods=["GET", "POST"], endpoint="login_redirect")
def login_redirect():
    return redirect(url_for("auth.login"))


@pages_bp.route("/auth/login", methods=["GET", "POST"], endpoint="auth.login")
def auth_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = DUMMY_USERS.get(username)
        if user and user["password"] == password:
            session["user"] = {
                "username": username,
                "role": user["role"],
                "name": user["name"],
                "employee_id": user["employee_id"],
            }
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials. Try emp001/emp@123 or hr001/hr@123", "danger")
    return render_template("login.html", title="Login – TaxPro HRMS")


@pages_bp.route("/auth/switch-role", methods=["POST"], endpoint="auth.switch_role")
def switch_role():
    if "user" not in session:
        return redirect(url_for("auth.login"))
    target_role = request.form.get("role")
    for uname, udata in DUMMY_USERS.items():
        if udata["role"] == target_role:
            session["user"] = {
                "username": uname,
                "role": udata["role"],
                "name": udata["name"],
                "employee_id": udata["employee_id"],
            }
            flash(f"Switched to {target_role.upper()} view as {udata['name']}", "info")
            break
    return redirect(url_for("dashboard"))


@pages_bp.route("/auth/logout", methods=["GET"], endpoint="auth.logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@pages_bp.route("/dashboard", methods=["GET"], endpoint="dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("auth.login"))
    user = session["user"]
    employees = pd.read_csv(CSV_EMPLOYEES, dtype=str).fillna("").to_dict(orient="records")

    metrics = None
    if user["role"] == "hr":
        from app.taxation.services.tax_service import get_hr_dashboard_metrics
        metrics = get_hr_dashboard_metrics(CURRENT_FY)

    return render_template(
        "dashboard.html",
        user=user,
        employees=employees,
        metrics=metrics,
        fy=CURRENT_FY,
        active_page="dashboard",
    )


@pages_bp.route("/uploads/<employee_id>/<filename>", methods=["GET"], endpoint="serve_upload")
def serve_upload(employee_id, filename):
    if "user" not in session:
        return redirect(url_for("auth.login"))

    user = session["user"]
    if user["role"] == "employee" and user["employee_id"] != employee_id:
        abort(403)

    employee_upload_dir = os.path.join(UPLOAD_FOLDER, employee_id)
    return send_from_directory(employee_upload_dir, filename)

# Export underlying APIRouter for registration
router = pages_bp.router
