"""Employee payslip and FNF routes."""
import io
from app.base.utils.flask_compat import render_template, session, redirect, url_for, flash, send_file
from app.payroll.services import payslip_service
from app.payroll.services.fnf_service import get_employee_settlements
from app.base.routers.blueprints import employee_bp, employee_required

@employee_bp.route("/payslips")
@employee_required
def history():
    user = session["user"]
    payslips = payslip_service.get_employee_payslips(user["employee_id"])
    return render_template("employee/payslips/history.html", payslips=payslips)

@employee_bp.route("/payslips/<payslip_id>")
@employee_required
def view_payslip(payslip_id):
    user = session["user"]
    details = payslip_service.get_payslip_details(payslip_id, user["employee_id"], "employee")
    if not details:
        flash("Payslip not found or access denied.", "danger")
        return redirect(url_for("employee.history"))
    return render_template("employee/payslips/view_payslip.html", **details)

@employee_bp.route("/payslips/<payslip_id>/download")
@employee_required
def download_payslip(payslip_id):
    user = session["user"]
    details = payslip_service.get_payslip_details(payslip_id, user["employee_id"], "employee")
    if not details:
        flash("Payslip not found or access denied.", "danger")
        return redirect(url_for("employee.history"))
        
    pdf_bytes = payslip_service.generate_payslip_pdf(details)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{payslip_id}.pdf"
    )

@employee_bp.route("/my-fnf")
@employee_required
def my_fnf():
    user = session["user"]
    from app.payroll.services.fnf_service import get_employee_settlements
    settlements = get_employee_settlements(user["employee_id"])
    return render_template("employee/my_fnf.html", user=user, settlements=settlements, active_page="my_fnf")
