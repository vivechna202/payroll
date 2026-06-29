"""
payroll_reports_routes.py – Read-only routes for Payroll Reports & Analytics.

Blueprint prefix: /hr/reports
"""

import io
from flask import Blueprint, render_template, session, redirect, url_for, flash, request, jsonify, send_file
from functools import wraps
from config import CURRENT_FY
from services.payroll_reports_service import (
    get_dashboard_analytics,
    get_chart_data,
    get_payroll_summary_report,
    get_department_payroll_report,
    get_employee_salary_history,
    get_contract_history,
    get_fnf_report,
    get_statutory_report,
    get_unique_departments_for_reports,
    get_all_batches_for_reports,
    get_unique_employees_for_reports,
    export_report_excel,
    export_report_csv,
)

reports_bp = Blueprint("reports", __name__, url_prefix="/hr/reports")


def hr_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = session.get("user")
        if not user or user.get("role") != "hr":
            flash("HR access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def _collect_filters():
    return {
        "fy": request.args.get("fy", CURRENT_FY),
        "month": request.args.get("month", ""),
        "department": request.args.get("department", ""),
        "employee_id": request.args.get("employee_id", ""),
        "batch_id": request.args.get("batch_id", ""),
    }


def _common_ctx():
    return {
        "departments": get_unique_departments_for_reports(),
        "batches": get_all_batches_for_reports(),
        "employees": get_unique_employees_for_reports(),
        "current_fy": CURRENT_FY,
    }


# ─────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────

@reports_bp.route("/dashboard")
@hr_required
def dashboard():
    user = session["user"]
    filters = _collect_filters()
    stats = get_dashboard_analytics(filters)
    ctx = _common_ctx()
    return render_template(
        "hr/reports/dashboard.html",
        user=user, stats=stats, filters=filters,
        active_page="reports_dashboard", **ctx
    )


@reports_bp.route("/api/charts")
@hr_required
def api_charts():
    filters = _collect_filters()
    data = get_chart_data(filters)
    return jsonify(data)


# ─────────────────────────────────────────────────────────────
# Payroll Reports
# ─────────────────────────────────────────────────────────────

@reports_bp.route("/payroll")
@hr_required
def payroll_report():
    user = session["user"]
    filters = _collect_filters()
    report_type = request.args.get("report_type", "monthly_summary")
    ctx = _common_ctx()

    if report_type == "department":
        rows = get_department_payroll_report(filters)
        title = "Department-wise Payroll Report"
    else:
        rows = get_payroll_summary_report(filters)
        title = "Monthly Payroll Summary"

    return render_template(
        "hr/reports/payroll_report.html",
        user=user, rows=rows, title=title,
        report_type=report_type, filters=filters,
        active_page="reports_payroll", **ctx
    )


# ─────────────────────────────────────────────────────────────
# Statutory Reports
# ─────────────────────────────────────────────────────────────

STATUTORY_TITLES = {
    "pf": "Provident Fund (PF) Report",
    "esi": "ESI Contribution Report",
    "pt": "Professional Tax (PT) Report",
    "lwf": "Labour Welfare Fund (LWF) Report",
    "tds": "TDS Deduction Report",
}

@reports_bp.route("/statutory/<component>")
@hr_required
def statutory_report(component):
    if component not in STATUTORY_TITLES:
        flash("Invalid report type.", "danger")
        return redirect(url_for("reports.dashboard"))
    user = session["user"]
    filters = _collect_filters()
    ctx = _common_ctx()
    rows = get_statutory_report(component, filters)
    title = STATUTORY_TITLES[component]
    return render_template(
        "hr/reports/statutory_report.html",
        user=user, rows=rows, title=title,
        component=component, filters=filters,
        active_page="reports_statutory", **ctx
    )


# ─────────────────────────────────────────────────────────────
# Employee Reports
# ─────────────────────────────────────────────────────────────

EMPLOYEE_REPORT_TITLES = {
    "salary_history": "Employee Salary History",
    "contract_history": "Contract History",
    "payslip_history": "Payslip History",
    "fnf_summary": "Full & Final Settlement Summary",
}

@reports_bp.route("/employee")
@hr_required
def employee_report():
    user = session["user"]
    filters = _collect_filters()
    report_type = request.args.get("report_type", "salary_history")
    ctx = _common_ctx()
    title = EMPLOYEE_REPORT_TITLES.get(report_type, "Employee Report")

    if report_type == "salary_history":
        rows = get_employee_salary_history(filters=filters)
    elif report_type == "contract_history":
        rows = get_contract_history(filters)
    elif report_type == "fnf_summary":
        rows = get_fnf_report(filters)
    else:
        rows = []

    return render_template(
        "hr/reports/employee_report.html",
        user=user, rows=rows, title=title,
        report_type=report_type, filters=filters,
        active_page="reports_employee", **ctx
    )


# ─────────────────────────────────────────────────────────────
# Export Endpoint
# ─────────────────────────────────────────────────────────────

@reports_bp.route("/export")
@hr_required
def export():
    fmt = request.args.get("format", "excel")
    report = request.args.get("report", "monthly_summary")
    component = request.args.get("component", "pf")
    filters = _collect_filters()

    # Choose data source
    if report == "department":
        data = get_department_payroll_report(filters)
        title = "Department_Payroll"
    elif report == "salary_history":
        data = get_employee_salary_history(filters=filters)
        title = "Employee_Salary_History"
    elif report == "contract_history":
        data = get_contract_history(filters)
        title = "Contract_History"
    elif report == "fnf_summary":
        data = get_fnf_report(filters)
        title = "FnF_Summary"
    elif report == "statutory":
        data = get_statutory_report(component, filters)
        title = f"Statutory_{component.upper()}"
    else:
        data = get_payroll_summary_report(filters)
        title = "Monthly_Payroll_Summary"

    fy_tag = filters.get("fy", CURRENT_FY)

    if fmt == "excel":
        raw = export_report_excel(data, title)
        return send_file(
            io.BytesIO(raw),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"{title}_{fy_tag}.xlsx"
        )
    elif fmt == "csv":
        raw = export_report_csv(data)
        return send_file(
            io.BytesIO(raw),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"{title}_{fy_tag}.csv"
        )
    elif fmt == "print":
        # Redirect to same page with print flag set
        return redirect(request.referrer or url_for("reports.dashboard"))

    flash("Invalid export format.", "danger")
    return redirect(url_for("reports.dashboard"))
