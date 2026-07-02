"""
ess_routes.py – Blueprints for Employee Self Service (ESS) & Manager Self Service (MSS).
"""

from app.base.utils.flask_compat import Blueprint, render_template, session, redirect, url_for, flash, request, abort
from functools import wraps
from app.base.utils.config import CURRENT_FY, CSV_EMPLOYEES, DUMMY_USERS
from app.ess.services.ess_service import (
    get_employee_dashboard_metrics,
    get_manager_dashboard_metrics,
    get_team_members,
    get_team_payroll_overview,
    get_employee_notifications,
    get_employee_documents,
    get_managed_employees,
    is_manager
)
from app.base.utils.csv_service import read_csv_row
from app.payroll.services.contract_service import get_active_contract, get_contracts_for_employee
from app.payroll.services.payslip_service import get_employee_payslips
from app.payroll.services.fnf_service import get_employee_settlements

# Monkeypatch Sneha Iyer as manager for local testing convenience
if "mgr001" not in DUMMY_USERS:
    DUMMY_USERS["mgr001"] = {
        "password": "mgr@123",
        "role": "manager",
        "name": "Sneha Iyer",
        "employee_id": "EMP003"
    }

ess_bp = Blueprint("ess", __name__, url_prefix="/ess")

# ─────────────────────────────────────────────────────────────
# Auth Guards
# ─────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

def manager_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        user = session["user"]
        # Allow managers and HR to access manager routes
        if user.get("role") not in ["manager", "hr"]:
            flash("Access denied. Manager role required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────
# Employee Self Service (ESS) Routes
# ─────────────────────────────────────────────────────────────

@ess_bp.route("/dashboard")
@login_required
def my_dashboard():
    user = session["user"]
    emp_id = user["employee_id"]
    
    metrics = get_employee_dashboard_metrics(emp_id)
    notifications = get_employee_notifications(emp_id)
    recent_payslips = get_employee_payslips(emp_id)[:3]
    
    return render_template(
        "employee/my_dashboard.html",
        user=user,
        metrics=metrics,
        notifications=notifications,
        recent_payslips=recent_payslips,
        fy=CURRENT_FY,
        active_page="ess_dashboard"
    )

@ess_bp.route("/profile")
@login_required
def my_profile():
    user = session["user"]
    emp_id = user["employee_id"]
    
    employee_data = read_csv_row(CSV_EMPLOYEES, "employee_id", emp_id)
    active_contract = get_active_contract(emp_id)
    
    return render_template(
        "employee/my_profile.html",
        user=user,
        employee=employee_data,
        active_contract=active_contract,
        fy=CURRENT_FY,
        active_page="ess_profile"
    )

@ess_bp.route("/contracts")
@login_required
def my_contracts():
    user = session["user"]
    emp_id = user["employee_id"]
    
    contracts = get_contracts_for_employee(emp_id)
    active_contract = get_active_contract(emp_id)
    
    return render_template(
        "employee/my_contracts.html",
        user=user,
        contracts=contracts,
        active_contract=active_contract,
        fy=CURRENT_FY,
        active_page="ess_contracts"
    )

@ess_bp.route("/salary-structure")
@login_required
def my_salary_structure():
    user = session["user"]
    emp_id = user["employee_id"]
    
    # Fetch active contract to get gross details
    active_contract = get_active_contract(emp_id)
    employee_data = read_csv_row(CSV_EMPLOYEES, "employee_id", emp_id)
    
    # Structure details preview from payroll service
    from app.payroll.services.payroll_service import get_employee_salary
    salary_structure = get_employee_salary(emp_id)
    
    return render_template(
        "employee/my_salary_structure.html",
        user=user,
        active_contract=active_contract,
        employee=employee_data,
        salary_structure=salary_structure,
        fy=CURRENT_FY,
        active_page="ess_salary_structure"
    )

@ess_bp.route("/payroll-history")
@login_required
def my_payroll_history():
    user = session["user"]
    emp_id = user["employee_id"]
    
    from app.payroll.services.payroll_service import get_employee_payroll
    payroll_history = get_employee_payroll(emp_id)
    
    return render_template(
        "employee/my_payroll_history.html",
        user=user,
        payroll_history=payroll_history,
        fy=CURRENT_FY,
        active_page="ess_payroll_history"
    )

@ess_bp.route("/documents")
@login_required
def my_documents():
    user = session["user"]
    emp_id = user["employee_id"]
    
    documents = get_employee_documents(emp_id)
    
    return render_template(
        "employee/my_documents.html",
        user=user,
        documents=documents,
        fy=CURRENT_FY,
        active_page="ess_documents"
    )

@ess_bp.route("/notifications")
@login_required
def my_notifications():
    user = session["user"]
    emp_id = user["employee_id"]
    
    notifications = get_employee_notifications(emp_id)
    
    return render_template(
        "employee/my_notifications.html",
        user=user,
        notifications=notifications,
        fy=CURRENT_FY,
        active_page="ess_notifications"
    )


# ─────────────────────────────────────────────────────────────
# Manager Self Service (MSS) Routes
# ─────────────────────────────────────────────────────────────

@ess_bp.route("/manager/dashboard")
@manager_required
def team_dashboard():
    user = session["user"]
    mgr_id = user["employee_id"]
    
    # HR is treated as a universal manager who reports to self / has full access
    if user.get("role") == "hr":
        # Let's map EMP003 (Sneha Iyer) as team for HR view demo
        mgr_id = "EMP003"
        
    metrics = get_manager_dashboard_metrics(mgr_id)
    team_members = get_team_members(mgr_id)
    
    # Dynamic counts for overview
    pending_approvals_count = metrics["pending_approvals"]
    
    return render_template(
        "manager/team_dashboard.html",
        user=user,
        metrics=metrics,
        team_members=team_members,
        pending_approvals_count=pending_approvals_count,
        fy=CURRENT_FY,
        active_page="mss_dashboard"
    )

@ess_bp.route("/manager/team")
@manager_required
def team_members():
    user = session["user"]
    mgr_id = user["employee_id"]
    if user.get("role") == "hr":
        mgr_id = "EMP003"
        
    team = get_team_members(mgr_id)
    
    return render_template(
        "manager/team_members.html",
        user=user,
        team=team,
        fy=CURRENT_FY,
        active_page="mss_team"
    )

@ess_bp.route("/manager/payroll")
@manager_required
def team_payroll():
    user = session["user"]
    mgr_id = user["employee_id"]
    if user.get("role") == "hr":
        mgr_id = "EMP003"
        
    payroll_history = get_team_payroll_overview(mgr_id)
    
    return render_template(
        "manager/team_payroll.html",
        user=user,
        payroll_history=payroll_history,
        fy=CURRENT_FY,
        active_page="mss_payroll"
    )

@ess_bp.route("/manager/contracts")
@manager_required
def team_contracts():
    user = session["user"]
    mgr_id = user["employee_id"]
    if user.get("role") == "hr":
        mgr_id = "EMP003"
        
    team = get_team_members(mgr_id)
    
    return render_template(
        "manager/team_contracts.html",
        user=user,
        team=team,
        fy=CURRENT_FY,
        active_page="mss_contracts"
    )

@ess_bp.route("/manager/profile/<employee_id>")
@manager_required
def employee_profile_view(employee_id):
    user = session["user"]
    mgr_id = user["employee_id"]
    
    # Security: Manager can access only employees reporting to them. HR has full access.
    if user.get("role") != "hr":
        managed_ids = get_managed_employees(mgr_id)
        if employee_id not in managed_ids:
            abort(403) # Forbidden
            
    employee_data = read_csv_row(CSV_EMPLOYEES, "employee_id", employee_id)
    active_contract = get_active_contract(employee_id)
    contract_history = get_contracts_for_employee(employee_id)
    
    return render_template(
        "manager/employee_profile.html",
        user=user,
        employee=employee_data,
        active_contract=active_contract,
        contract_history=contract_history,
        fy=CURRENT_FY,
        active_page="mss_team"
    )

@ess_bp.route("/manager/approvals")
@manager_required
def approval_dashboard():
    user = session["user"]
    mgr_id = user["employee_id"]
    if user.get("role") == "hr":
        mgr_id = "EMP003"
        
    managed_ids = get_managed_employees(mgr_id)
    
    # Fetch pending investment proofs for managed employees
    from app.base.utils.config import CSV_PROOFS
    proofs_df = read_csv_row
    from app.base.utils.csv_service import read_csv
    all_proofs_df = read_csv(CSV_PROOFS)
    
    pending_proofs = []
    if not all_proofs_df.empty and managed_ids:
        filtered = all_proofs_df[(all_proofs_df["employee_id"].isin(managed_ids)) & (all_proofs_df["status"] == "PENDING")]
        pending_proofs = filtered.to_dict(orient="records")
        
    return render_template(
        "manager/approvals.html",
        user=user,
        pending_proofs=pending_proofs,
        fy=CURRENT_FY,
        active_page="mss_approvals"
    )
