"""HR payroll routes (legacy processing + register)."""
from flask import render_template, session, redirect, url_for, flash, request, send_file
import io
from datetime import date
from app.base.utils.config import CURRENT_FY
from app.payroll.services.payroll_service import (
    get_payroll_summary, get_all_employee_salaries, process_monthly_payroll,
    get_employee_salary, update_employee_salary,
)
from app.payroll.services.payroll_register_service import (
    get_payroll_register_data, get_register_dashboard_stats,
    export_to_excel, export_to_csv, get_unique_departments,
)
from app.base.routers.blueprints import hr_bp, hr_required


@hr_bp.route("/payroll-processing", methods=["GET", "POST"])
@hr_required
def payroll_processing():
    user = session["user"]
    today = date.today()
    month = request.args.get("month", str(today.month))
    fy = request.args.get("fy", CURRENT_FY)

    summary = get_payroll_summary(month, fy)
    employees = get_all_employee_salaries()

    if request.method == "POST":
        result = process_monthly_payroll(
            request.form.get("month", month),
            request.form.get("fy", fy)
        )
        flash(f"Payroll run triggered. {result['message']}", "info")
        return redirect(url_for("hr.payroll_processing", month=month, fy=fy))

    return render_template(
        "hr/payroll_processing.html",
        user=user,
        summary=summary,
        employees=employees,
        selected_month=month,
        fy=fy,
        active_page="payroll_processing",
    )


@hr_bp.route("/payroll-edit/<employee_id>", methods=["GET", "POST"])
@hr_required
def payroll_edit(employee_id):
    user = session["user"]
    salary = get_employee_salary(employee_id)

    if request.method == "POST":
        basic = float(request.form.get("basic_salary", 0))
        hra = float(request.form.get("hra", 0))
        special = float(request.form.get("special_allowance", 0))
        other = float(request.form.get("other_allowances", 0))

        tds_regime = request.form.get("tds_regime", "NEW")
        section_80C = float(request.form.get("section_80C", 0))
        section_80D = float(request.form.get("section_80D", 0))
        hra_exemption = float(request.form.get("hra_exemption", 0))

        update_employee_salary(employee_id, basic, hra, special, other, tds_regime, section_80C, section_80D, hra_exemption)
        flash(f"Salary updated for {employee_id}.", "success")
        return redirect(url_for("hr.payroll_processing"))

    return render_template(
        "hr/payroll_edit.html",
        user=user,
        employee_id=employee_id,
        salary=salary,
        fy=CURRENT_FY,
        active_page="payroll_processing",
    )


@hr_bp.route("/payroll-register")
@hr_required
def payroll_register():
    user = session["user"]

    filters = {
        "month": request.args.get("month", ""),
        "fy": request.args.get("fy", CURRENT_FY),
        "employee_id": request.args.get("employee_id", "").strip(),
        "department": request.args.get("department", ""),
        "batch_id": request.args.get("batch_id", ""),
        "payroll_status": request.args.get("payroll_status", "")
    }

    data = get_payroll_register_data(filters)
    stats = get_register_dashboard_stats(data)
    departments = get_unique_departments()

    return render_template(
        "hr/payroll_register.html",
        user=user,
        payrolls=data,
        stats=stats,
        filters=filters,
        departments=departments,
        fy=CURRENT_FY,
        active_page="payroll_register",
    )


@hr_bp.route("/payroll-register/export/<format>")
@hr_required
def payroll_register_export(format):
    filters = {
        "month": request.args.get("month", ""),
        "fy": request.args.get("fy", CURRENT_FY),
        "employee_id": request.args.get("employee_id", "").strip(),
        "department": request.args.get("department", ""),
        "batch_id": request.args.get("batch_id", ""),
        "payroll_status": request.args.get("payroll_status", "")
    }

    data = get_payroll_register_data(filters)

    if format == "excel":
        excel_bytes = export_to_excel(data)
        return send_file(
            io.BytesIO(excel_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=f"Payroll_Register_{filters['fy']}.xlsx"
        )
    elif format == "csv":
        csv_bytes = export_to_csv(data)
        return send_file(
            io.BytesIO(csv_bytes),
            mimetype="text/csv",
            as_attachment=True,
            download_name=f"Payroll_Register_{filters['fy']}.csv"
        )

    flash("Invalid export format.", "danger")
    return redirect(url_for("hr.payroll_register"))
