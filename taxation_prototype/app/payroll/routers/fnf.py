from app.base.utils.flask_compat import Blueprint, render_template, session, redirect, url_for, flash, request
from functools import wraps
from app.base.utils.config import CURRENT_FY
from app.payroll.services.fnf_service import (
    get_dashboard_stats, get_all_settlements, create_settlement, 
    get_settlement_details, update_settlement_status, calculate_fnf_components
)
from app.base.utils.csv_service import get_all_employees

fnf_bp = Blueprint("fnf", __name__, url_prefix="/hr/fnf")

def hr_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get("user")
        if not user or user.get("role") != "hr":
            flash("Unauthorized access. HR role required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated_function

@fnf_bp.route("/dashboard")
@hr_required
def dashboard():
    user = session["user"]
    stats = get_dashboard_stats(CURRENT_FY)
    return render_template("hr/fnf/dashboard.html", user=user, stats=stats, active_page="fnf_dashboard")

@fnf_bp.route("/")
@hr_required
def list_settlements():
    user = session["user"]
    settlements = get_all_settlements()
    return render_template("hr/fnf/list.html", user=user, settlements=settlements, active_page="fnf_list")

@fnf_bp.route("/create", methods=["GET", "POST"])
@hr_required
def create():
    user = session["user"]
    employees = get_all_employees()
    
    if request.method == "POST":
        employee_id = request.form.get("employee_id")
        lwd = request.form.get("last_working_date")
        
        # If the form submits specific overrides (from a preview step), we use them
        if request.form.get("action") == "save":
            overrides = {
                "pending_salary": request.form.get("pending_salary", 0),
                "notice_period_amount": request.form.get("notice_period_amount", 0),
                "leave_encashment": request.form.get("leave_encashment", 0),
                "gratuity": request.form.get("gratuity", 0),
                "bonus_incentives": request.form.get("bonus_incentives", 0),
                "other_recoveries": request.form.get("other_recoveries", 0),
                "remarks": request.form.get("remarks", "")
            }
            res = create_settlement(employee_id, lwd, user["name"], overrides)
            if res["status"] == "success":
                flash(res["message"], "success")
                return redirect(url_for("fnf.view", settlement_id=res["settlement_id"]))
            else:
                flash(res["message"], "danger")
                
        elif request.form.get("action") == "calculate":
            calc = calculate_fnf_components(employee_id, lwd)
            selected_emp = next((e for e in employees if e["employee_id"] == employee_id), None)
            return render_template("hr/fnf/create.html", user=user, employees=employees, 
                                   calc=calc, employee_id=employee_id, lwd=lwd, selected_emp=selected_emp, active_page="fnf_create")

    return render_template("hr/fnf/create.html", user=user, employees=employees, active_page="fnf_create")

@fnf_bp.route("/view/<settlement_id>")
@hr_required
def view(settlement_id):
    user = session["user"]
    data = get_settlement_details(settlement_id)
    if not data:
        flash("Settlement not found.", "danger")
        return redirect(url_for("fnf.list_settlements"))
        
    return render_template("hr/fnf/view.html", user=user, data=data, active_page="fnf_list")

@fnf_bp.route("/status/<settlement_id>", methods=["POST"])
@hr_required
def change_status(settlement_id):
    user = session["user"]
    action = request.form.get("action")
    
    status_map = {
        "review": "Under Review",
        "approve": "Approved",
        "reject": "Rejected",
        "pay": "Paid",
        "cancel": "Cancelled"
    }
    
    new_status = status_map.get(action)
    if new_status:
        res = update_settlement_status(settlement_id, new_status, user["name"])
        flash(res["message"], res["status"])
    else:
        flash("Invalid action.", "danger")
        
    return redirect(url_for("fnf.view", settlement_id=settlement_id))
