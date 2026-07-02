"""
payroll_engine_routes.py - Enterprise Payroll Processing Engine (Batches)
Routes for /hr/payroll-engine
"""
from app.base.utils.flask_compat import Blueprint, render_template, request, redirect, url_for, flash, session
from functools import wraps
from datetime import datetime
import json
from app.base.utils.csv_service import read_csv_filtered
from app.base.utils.config import CURRENT_FY, CSV_EMPLOYEES
from app.payroll.services.payroll_service import (
    get_all_batches, get_batch_by_id, create_payroll_batch, 
    update_batch_status, mark_batch_ready, process_batch, recalculate_batch,
    lock_batch, unlock_batch, cancel_batch, get_batch_entries, 
    get_employee_payroll_history, get_payroll_engine_dashboard, get_batch_summary
)

def get_employee_by_id(employee_id):
    df = read_csv_filtered(CSV_EMPLOYEES, "employee_id", employee_id)
    if df.empty:
        return None
    return df.iloc[0].to_dict()

payroll_engine_bp = Blueprint("payroll_engine", __name__, url_prefix="/hr/payroll-engine")

def hr_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        if session["user"].get("role") != "hr":
            flash("HR access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

@payroll_engine_bp.route("/")
@hr_required
def dashboard():
    fy = request.args.get("fy", CURRENT_FY)
    stats = get_payroll_engine_dashboard(fy)
    batches = get_all_batches(fy=fy)
    return render_template(
        "hr/payroll/batches_list.html",
        user=session["user"],
        stats=stats,
        batches=batches,
        fy=fy,
        active_page="payroll_engine"
    )

@payroll_engine_bp.route("/batches/new", methods=["GET", "POST"])
@hr_required
def new_batch():
    if request.method == "POST":
        month = int(request.form.get("month"))
        year = int(request.form.get("year"))
        fy = request.form.get("fy", CURRENT_FY)
        description = request.form.get("description", "")
        
        res = create_payroll_batch(month, year, fy, session["user"]["name"], description)
        if res.get("status") == "success":
            flash(res["message"], "success")
            return redirect(url_for("payroll_engine.batch_detail", batch_id=res["batch_id"]))
        else:
            flash(res["message"], "danger")
            
    now = datetime.now()
    return render_template(
        "hr/payroll/batch_form.html",
        user=session["user"],
        current_month=now.month,
        current_year=now.year,
        fy=CURRENT_FY,
        active_page="payroll_engine"
    )

@payroll_engine_bp.route("/batches/<batch_id>")
@hr_required
def batch_detail(batch_id):
    batch = get_batch_by_id(batch_id)
    if not batch:
        flash("Batch not found.", "danger")
        return redirect(url_for("payroll_engine.dashboard"))
        
    entries = get_batch_entries(batch_id)
    # Add employee info to entries
    for entry in entries:
        emp = get_employee_by_id(entry["employee_id"])
        entry["employee_name"] = emp.get("name", "Unknown") if emp else "Unknown"
        
    summary = get_batch_summary(batch_id)
        
    return render_template(
        "hr/payroll/batch_detail.html",
        user=session["user"],
        batch=batch,
        entries=entries,
        summary=summary,
        active_page="payroll_engine"
    )

@payroll_engine_bp.route("/batches/<batch_id>/validate", methods=["POST"])
@hr_required
def validate_batch(batch_id):
    res = mark_batch_ready(batch_id, session["user"]["name"])
    if res.get("status") == "success":
        flash("Batch validated and marked Ready.", "success")
    else:
        flash(res["message"], "danger")
    return redirect(url_for("payroll_engine.batch_detail", batch_id=batch_id))

@payroll_engine_bp.route("/batches/<batch_id>/process", methods=["POST"])
@hr_required
def run_process_batch(batch_id):
    res = process_batch(batch_id, session["user"]["name"])
    if res.get("status") == "success":
        flash(res["message"], "success")
    else:
        flash(res["message"], "danger")
    return redirect(url_for("payroll_engine.batch_detail", batch_id=batch_id))

@payroll_engine_bp.route("/batches/<batch_id>/recalculate", methods=["POST"])
@hr_required
def run_recalculate_batch(batch_id):
    res = recalculate_batch(batch_id, session["user"]["name"])
    if res.get("status") == "success":
        flash("Batch recalculated successfully.", "success")
    else:
        flash(res["message"], "danger")
    return redirect(url_for("payroll_engine.batch_detail", batch_id=batch_id))

@payroll_engine_bp.route("/batches/<batch_id>/lock", methods=["POST"])
@hr_required
def run_lock_batch(batch_id):
    res = lock_batch(batch_id, session["user"]["name"])
    if res.get("status") == "success":
        flash("Batch locked successfully.", "success")
    else:
        flash(res["message"], "danger")
    return redirect(url_for("payroll_engine.batch_detail", batch_id=batch_id))

@payroll_engine_bp.route("/batches/<batch_id>/unlock", methods=["POST"])
@hr_required
def run_unlock_batch(batch_id):
    res = unlock_batch(batch_id, session["user"]["name"])
    if res.get("status") == "success":
        flash("Batch unlocked.", "info")
    else:
        flash(res["message"], "danger")
    return redirect(url_for("payroll_engine.batch_detail", batch_id=batch_id))

@payroll_engine_bp.route("/batches/<batch_id>/cancel", methods=["POST"])
@hr_required
def run_cancel_batch(batch_id):
    res = cancel_batch(batch_id, session["user"]["name"])
    if res.get("status") == "success":
        flash("Batch cancelled.", "info")
    else:
        flash(res["message"], "danger")
    return redirect(url_for("payroll_engine.batch_detail", batch_id=batch_id))

@payroll_engine_bp.route("/batches/<batch_id>/entries/<payroll_id>")
@hr_required
def entry_detail(batch_id, payroll_id):
    batch = get_batch_by_id(batch_id)
    if not batch:
        flash("Batch not found.", "danger")
        return redirect(url_for("payroll_engine.dashboard"))
        
    entries = get_batch_entries(batch_id)
    entry = next((e for e in entries if e["payroll_id"] == payroll_id), None)
    if not entry:
        flash("Entry not found.", "danger")
        return redirect(url_for("payroll_engine.batch_detail", batch_id=batch_id))
        
    emp = get_employee_by_id(entry["employee_id"])
    entry["employee_name"] = emp.get("name", "Unknown") if emp else "Unknown"
    
    earnings = json.loads(entry.get("earnings_json", "[]")) if entry.get("earnings_json") else []
    deductions = json.loads(entry.get("deductions_json", "[]")) if entry.get("deductions_json") else []
    
    return render_template(
        "hr/payroll/entry_detail.html",
        user=session["user"],
        batch=batch,
        entry=entry,
        earnings=earnings,
        deductions=deductions,
        active_page="payroll_engine"
    )

@payroll_engine_bp.route("/employee/<employee_id>")
@hr_required
def employee_history(employee_id):
    emp = get_employee_by_id(employee_id)
    if not emp:
        flash("Employee not found.", "danger")
        return redirect(url_for("payroll_engine.dashboard"))
        
    fy = request.args.get("fy", CURRENT_FY)
    history = get_employee_payroll_history(employee_id, fy=fy)
    
    return render_template(
        "hr/payroll/employee_history.html",
        user=session["user"],
        employee=emp,
        history=history,
        fy=fy,
        active_page="payroll_engine"
    )
