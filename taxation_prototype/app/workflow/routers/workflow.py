"""
workflow_routes.py – Blueprints for workflows and notifications.
"""

import json
from fastapi import Request

from app.base.utils.flask_compat import Blueprint, render_template, session, redirect, url_for, flash, abort, jsonify
from functools import wraps
from app.base.utils.config import CURRENT_FY
from app.workflow.services.workflow_service import (
    get_all_workflow_requests, get_workflow_request, get_workflow_history,
    get_pending_approvals, process_approval, cancel_workflow_request,
    create_workflow_request
)
from app.workflow.services.notification_service import (
    get_notifications, mark_as_read, mark_all_as_read, get_unread_count
)

workflow_bp = Blueprint("workflow", __name__, url_prefix="/hr/workflow")
notifications_bp = Blueprint("notifications", __name__, url_prefix="/employee/notifications")

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

def hr_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        user = session["user"]
        if user.get("role") != "hr":
            flash("Access denied. HR role required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────
# Context Processor for Badge counts
# ─────────────────────────────────────────────────────────────
# Note: app_context_processor is handled in the CompatRouter's _template_context function
# in flask_compat.py. The notification badge count is already injected there.


# ─────────────────────────────────────────────────────────────
# Workflow HR routes
# ─────────────────────────────────────────────────────────────

@workflow_bp.route("/dashboard")
@hr_required
def dashboard():
    user = session["user"]
    requests = get_all_workflow_requests()
    
    # Calculate statistics
    pending = [r for r in requests if r["status"] in ["Submitted", "Pending Approval"]]
    approved = [r for r in requests if r["status"] == "Completed"]
    rejected = [r for r in requests if r["status"] == "Rejected"]
    cancelled = [r for r in requests if r["status"] == "Cancelled"]
    
    stats = {
        "pending_count": len(pending),
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "cancelled_count": len(cancelled),
        "total_count": len(requests)
    }
    
    return render_template(
        "hr/workflow/dashboard.html",
        user=user,
        requests=requests,
        stats=stats,
        fy=CURRENT_FY,
        active_page="workflow_dashboard"
    )

@workflow_bp.route("/")
@hr_required
def list_requests():
    user = session["user"]
    requests = get_all_workflow_requests()
    return render_template(
        "hr/workflow/list.html",
        user=user,
        requests=requests,
        fy=CURRENT_FY,
        active_page="workflow_list"
    )

@workflow_bp.route("/view/<request_id>")
@login_required
def view_request(request_id):
    user = session["user"]
    req = get_workflow_request(request_id)
    if not req:
        flash("Workflow request not found.", "danger")
        return redirect(url_for("workflow.list_requests") if user["role"] == "hr" else url_for("dashboard"))
        
    # Security: Employees can view only their own requests, Managers only their team, HR all.
    if user["role"] == "employee" and req["employee_id"] != user["employee_id"]:
        abort(403)
    elif user["role"] == "manager":
        from app.ess.services.ess_service import get_managed_employees
        managed_ids = get_managed_employees(user["employee_id"])
        if req["employee_id"] not in managed_ids and req["employee_id"] != user["employee_id"]:
            abort(403)
            
    history = get_workflow_history(request_id)
    steps = json.loads(req["steps_json"])
    
    # Check if current user is the current active approver
    current_step_num = int(req["current_step"])
    is_current_approver = False
    for s in steps:
        if s["step_num"] == current_step_num and s["status"] == "Pending Approval":
            if s["approver"] == user["employee_id"] or (s["approver"] == "hr" and user["role"] == "hr"):
                is_current_approver = True
                break
                
    return render_template(
        "hr/workflow/detail.html",
        user=user,
        req=req,
        history=history,
        steps=steps,
        is_current_approver=is_current_approver,
        fy=CURRENT_FY,
        active_page="workflow_list"
    )

@workflow_bp.route("/action/<request_id>", methods=["POST"])
@login_required
async def action_request(request_id, request: Request):
    user = session["user"]
    form = await request.form()
    action = form.get("action")  # Approve, Reject, Send Back
    comment = form.get("comment", "")
    
    # Use role name 'hr' if user is HR for role checking
    approver_id = "hr" if user["role"] == "hr" else user["employee_id"]
    
    res = process_approval(request_id, approver_id, action, comment)
    flash(res["message"], "success" if res["status"] == "success" else "danger")
    
    return redirect(url_for("workflow.view_request", request_id=request_id))

@workflow_bp.route("/cancel/<request_id>", methods=["POST"])
@login_required
def cancel_request(request_id):
    user = session["user"]
    # Pass 'hr' role string or specific employee id
    employee_id = "hr" if user["role"] == "hr" else user["employee_id"]
    
    res = cancel_workflow_request(request_id, employee_id)
    flash(res["message"], "success" if res["status"] == "success" else "danger")
    
    return redirect(url_for("workflow.view_request", request_id=request_id))


# ─────────────────────────────────────────────────────────────
# Notification Routes
# ─────────────────────────────────────────────────────────────

@notifications_bp.route("/")
@login_required
def list_notifications():
    user = session["user"]
    
    # HR gets both their employee ID notifications and general 'hr' notifications
    notifications = get_notifications(user["employee_id"])
    if user["role"] == "hr":
        notifications += get_notifications("hr")
        # Sort combined notifications by timestamp desc
        notifications.sort(key=lambda x: x["timestamp"], reverse=True)
        
    return render_template(
        "employee/notifications/list.html",
        user=user,
        notifications=notifications,
        fy=CURRENT_FY,
        active_page="notifications_list"
    )

@notifications_bp.route("/read/<notification_id>", methods=["POST"])
@login_required
def mark_read_route(notification_id):
    mark_as_read(notification_id)
    return jsonify({"status": "success"})

@notifications_bp.route("/mark-all-read", methods=["POST"])
@login_required
def mark_all_read_route():
    user = session["user"]
    mark_all_as_read(user["employee_id"])
    if user["role"] == "hr":
        mark_all_as_read("hr")
    flash("All notifications marked as read.", "success")
    return redirect(url_for("notifications.list_notifications"))
