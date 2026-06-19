"""
app.py – Application entry point for the Employee Taxation Prototype.

Run:
    python app.py

Phase 2 Integration Points:
  - Replace CSV initialisation with Alembic migrations + PostgreSQL.
  - Add Flask-Login for production-grade auth.
  - Add Celery for async payroll / TDS computation jobs.
"""

import os
from flask import Flask, render_template, session, redirect, url_for, request, flash, send_from_directory, abort , jsonify
from config import (
    SECRET_KEY, DEBUG, UPLOAD_FOLDER, GENERATED_FOLDER,
    FORM16_FOLDER, FORM24Q_FOLDER, DUMMY_DATA_FOLDER,
    CSV_EMPLOYEES, CSV_DECLARATIONS, CSV_DECLARATION_ITEMS, CSV_PROOFS, CSV_PAYROLL, CSV_EMPLOYEE_SALARY,
    CSV_TDS, CSV_DECLARATION_WINDOWS, CSV_FORM16, CSV_FORM16_HISTORY,
    DUMMY_USERS, CURRENT_FY, CSV_CHALLANS, CSV_DEDUCTOR_MASTER, CSI_FOLDER,
    FORM16_PROCESSING_FOLDER, CSV_FORM16_PROCESSING_LOG, FORM16_MERGED_FOLDER
)
from services.csv_service import ensure_csv

# ─────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

# ─────────────────────────────────────────────────────────────
# Ensure directories exist
# ─────────────────────────────────────────────────────────────

for _dir in [UPLOAD_FOLDER, GENERATED_FOLDER, FORM16_FOLDER,
             FORM24Q_FOLDER, DUMMY_DATA_FOLDER, CSI_FOLDER,
             FORM16_PROCESSING_FOLDER, FORM16_MERGED_FOLDER]:
    os.makedirs(_dir, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# Initialise CSV files with headers (idempotent)
# ─────────────────────────────────────────────────────────────

ensure_csv(CSV_EMPLOYEES, [
    "employee_id", "name", "email", "department", "designation",
    "date_of_joining", "pan", "uan", "bank_account", "ifsc", "status",
])

ensure_csv(CSV_DECLARATIONS, [
    "declaration_id", "employee_id", "financial_year", "tax_regime", 
    "status", "submitted_at", "updated_at"
])

ensure_csv(CSV_DECLARATION_ITEMS, [
    "declaration_id", "section", "amount"
])

ensure_csv(CSV_PROOFS, [
    "proof_id", "employee_id", "declaration_id", "section",
    "file_name", "file_path", "status", "hr_remarks",
    "uploaded_at", "reviewed_at"
])

ensure_csv(CSV_PAYROLL, [
    "payroll_id", "employee_id", "financial_year", "month",
    "basic_salary", "hra", "special_allowance", "other_allowances",
    "gross_salary", "employee_pf", "professional_tax", "tds", "net_salary",
    "payroll_status", "processed_at",
])

ensure_csv(CSV_EMPLOYEE_SALARY, [
    "employee_id", "basic_salary", "hra", "special_allowance",
    "other_allowances", "effective_from",
    "tds_regime", "section_80C", "section_80D", "hra_exemption"
])

ensure_csv(CSV_TDS, [
    "tds_id", "employee_id", "financial_year", "month", "tax_regime",
    "annual_taxable_income", "estimated_annual_tax", "annual_tds",
    "monthly_tds", "payroll_id", "calculated_at"
])

ensure_csv(CSV_DECLARATION_WINDOWS, [
    "window_id", "fy", "window_type", "start_date",
    "end_date", "created_by", "created_on", "status",
])

ensure_csv(CSV_FORM16, [
    "form16_id", "employee_id", "fy", "generated_on",
    "generated_by", "filename", "filepath", "status",
])

ensure_csv(CSV_FORM16_HISTORY, [
    "generation_id", "employee_id", "financial_year",
    "generated_by", "generated_at", "file_name"
])

# Form 16 Processing audit log (separate from existing Form 16 module)
ensure_csv(CSV_FORM16_PROCESSING_LOG, [
    "log_id", "session_id", "event_type", "filename",
    "status", "pan", "employee_name", "financial_year",
    "part_type", "error_detail", "timestamp"
])

from config import CSV_FORM24Q_HISTORY
ensure_csv(CSV_FORM24Q_HISTORY, [
    "generation_id", "financial_year", "quarter", "generated_by",
    "generated_at", "file_name"
])

ensure_csv(CSV_CHALLANS, [
    "challan_id",
    "quarter",
    "financial_year",
    "bsr_code",
    "challan_serial_no",
    "challan_date",
    "challan_amount",
    "section_code",
    "status"
])

ensure_csv(CSV_DEDUCTOR_MASTER, [
    "tan",
    "pan",
    "company_name",
    "address",
    "state",
    "pin_code",
    "contact_person",
    "contact_email"
])

# ─────────────────────────────────────────────────────────────
# Seed sample employee records (only if employees.csv is empty)
# ─────────────────────────────────────────────────────────────

import pandas as pd

_emp_df = pd.read_csv(CSV_EMPLOYEES, dtype=str).fillna("")
if _emp_df.empty:
    sample_employees = [
        {
            "employee_id": "EMP001", "name": "Priya Sharma",
            "email": "priya.sharma@company.com",
            "department": "Engineering", "designation": "Software Engineer",
            "date_of_joining": "2021-07-01", "pan": "ABCPS1234D",
            "uan": "100456789012", "bank_account": "9876543210",
            "ifsc": "SBIN0001234", "status": "ACTIVE",
        },
        {
            "employee_id": "EMP002", "name": "Arjun Mehta",
            "email": "arjun.mehta@company.com",
            "department": "Finance", "designation": "Financial Analyst",
            "date_of_joining": "2020-03-15", "pan": "BCDAM5678E",
            "uan": "100456789013", "bank_account": "8765432109",
            "ifsc": "HDFC0002345", "status": "ACTIVE",
        },
        {
            "employee_id": "EMP003", "name": "Sneha Iyer",
            "email": "sneha.iyer@company.com",
            "department": "HR", "designation": "HR Manager",
            "date_of_joining": "2019-11-01", "pan": "CDPSI9012F",
            "uan": "100456789014", "bank_account": "7654321098",
            "ifsc": "ICIC0003456", "status": "ACTIVE",
        },
        {
            "employee_id": "EMP004", "name": "Karan Gupta",
            "email": "karan.gupta@company.com",
            "department": "Sales", "designation": "Sales Executive",
            "date_of_joining": "2022-08-01", "pan": "DEPKG3456G",
            "uan": "100456789015", "bank_account": "6543210987",
            "ifsc": "AXIS0004567", "status": "ACTIVE",
        },
        {
            "employee_id": "HR001", "name": "Rahul Verma",
            "email": "rahul.verma@company.com",
            "department": "HR", "designation": "HR Director",
            "date_of_joining": "2018-01-10", "pan": "EFPRV7890H",
            "uan": "100456789016", "bank_account": "5432109876",
            "ifsc": "KOTAK0005678", "status": "ACTIVE",
        },
    ]
    pd.DataFrame(sample_employees).to_csv(CSV_EMPLOYEES, index=False)
    
    sample_salaries = [
        {"employee_id": "EMP001", "basic_salary": 50000, "hra": 20000, "special_allowance": 17000, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
        {"employee_id": "EMP002", "basic_salary": 37500, "hra": 15000, "special_allowance": 12000, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
        {"employee_id": "EMP003", "basic_salary": 62500, "hra": 25000, "special_allowance": 20833, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
        {"employee_id": "EMP004", "basic_salary": 25000, "hra": 10000, "special_allowance": 8000, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
        {"employee_id": "HR001", "basic_salary": 83333, "hra": 33333, "special_allowance": 27778, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
    ]
    pd.DataFrame(sample_salaries).to_csv(CSV_EMPLOYEE_SALARY, index=False)

# ─────────────────────────────────────────────────────────────
# Register blueprints
# ─────────────────────────────────────────────────────────────

from routes.employee_routes import employee_bp
from routes.hr_routes import hr_bp
from routes.form16_processing_routes import form16_processing_bp

app.register_blueprint(employee_bp)
app.register_blueprint(hr_bp)
app.register_blueprint(form16_processing_bp)

# Cleanup stale Form 16 Processing temp sessions on startup
from services.form16_processing_service import cleanup_stale_sessions
cleanup_stale_sessions(max_age_hours=24)

# ─────────────────────────────────────────────────────────────
# Auth routes
# ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("auth.login"))


@app.route("/login", methods=["GET", "POST"])
def login_redirect():
    return redirect(url_for("auth.login"))


@app.route("/auth/login", methods=["GET", "POST"], endpoint="auth.login")
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


@app.route("/auth/switch-role", methods=["POST"], endpoint="auth.switch_role")
def switch_role():
    """Demo convenience: switch between employee and HR views."""
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


@app.route("/auth/logout", endpoint="auth.logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("auth.login"))
    user = session["user"]
    employees = pd.read_csv(CSV_EMPLOYEES, dtype=str).fillna("").to_dict(orient="records")
    
    metrics = None
    if user["role"] == "hr":
        from services.tax_service import get_hr_dashboard_metrics
        metrics = get_hr_dashboard_metrics(CURRENT_FY)
        
    return render_template(
        "dashboard.html",
        user=user,
        employees=employees,
        metrics=metrics,
        fy=CURRENT_FY,
        active_page="dashboard",
    )


# ─────────────────────────────────────────────────────────────
# Error handlers
# ─────────────────────────────────────────────────────────────

@app.route("/uploads/<employee_id>/<filename>")
def serve_upload(employee_id, filename):
    if "user" not in session:
        return redirect(url_for("auth.login"))
        
    user = session["user"]
    # RBAC check: HR can see all, Employee can only see their own
    if user["role"] == "employee" and user["employee_id"] != employee_id:
        abort(403)
        
    employee_upload_dir = os.path.join(app.config["UPLOAD_FOLDER"], employee_id)
    return send_from_directory(employee_upload_dir, filename)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403


# ─────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=DEBUG, port=5050)
