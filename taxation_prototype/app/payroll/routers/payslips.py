import io
from app.base.utils.flask_compat import Blueprint, render_template, request, redirect, url_for, flash, send_file, session
from app.payroll.services import payslip_service
from app.payroll.services import payroll_service
from app.base.utils.config import CURRENT_FY
from app.base.routers.blueprints import hr_required

payslips_bp = Blueprint("payslips", __name__, url_prefix="/hr/payslips")

@payslips_bp.route("/dashboard")
@hr_required
def dashboard():
    stats = payslip_service.get_dashboard_stats(CURRENT_FY)
    batches = payroll_service.get_all_batches(fy=CURRENT_FY)
    # only show PROCESSED or LOCKED batches to generate payslips for
    ready_batches = [b for b in batches if b.get("status") in ["PROCESSED", "LOCKED", "Done"]]
    return render_template("hr/payslips/dashboard.html", stats=stats, batches=ready_batches)

@payslips_bp.route("/batch/<batch_id>")
@hr_required
def batch_payslips(batch_id):
    batch = payroll_service.get_batch_by_id(batch_id)
    if not batch:
        flash("Batch not found.", "danger")
        return redirect(url_for("payslips.dashboard"))
        
    payslips = payslip_service.get_payslips_by_batch(batch_id)
    return render_template("hr/payslips/batch_payslips.html", batch=batch, payslips=payslips)

@payslips_bp.route("/generate/batch/<batch_id>", methods=["POST"])
@hr_required
def generate_batch(batch_id):
    user = session["user"]["employee_id"]
    res = payslip_service.generate_batch_payslips(batch_id, user)
    if res["status"] == "success":
        flash(res["message"], "success")
    else:
        flash(res["message"], "danger")
    return redirect(url_for("payslips.batch_payslips", batch_id=batch_id))

@payslips_bp.route("/generate/individual/<payroll_id>", methods=["POST"])
@hr_required
def generate_individual(payroll_id):
    user = session["user"]["employee_id"]
    res = payslip_service.generate_individual_payslip(payroll_id, user)
    if res["status"] == "success":
        flash(res["message"], "success")
    else:
        flash(res["message"], "danger")
    # Redirect back to referring page
    return redirect(request.referrer or url_for("payslips.dashboard"))

@payslips_bp.route("/view/<payslip_id>")
@hr_required
def view_payslip(payslip_id):
    user_id = session["user"]["employee_id"]
    details = payslip_service.get_payslip_details(payslip_id, user_id, "hr")
    if not details:
        flash("Payslip not found.", "danger")
        return redirect(url_for("payslips.dashboard"))
    return render_template("hr/payslips/view_payslip.html", **details)

@payslips_bp.route("/download/<payslip_id>")
@hr_required
def download_payslip(payslip_id):
    user_id = session["user"]["employee_id"]
    details = payslip_service.get_payslip_details(payslip_id, user_id, "hr")
    if not details:
        flash("Payslip not found.", "danger")
        return redirect(url_for("payslips.dashboard"))
        
    pdf_bytes = payslip_service.generate_payslip_pdf(details)
    return send_file(
        io.BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"{payslip_id}.pdf"
    )

@payslips_bp.route("/status/<payslip_id>", methods=["POST"])
@hr_required
def update_status(payslip_id):
    status = request.form.get("status")
    user = session["user"]["employee_id"]
    res = payslip_service.update_payslip_status(payslip_id, status, user)
    if res["status"] == "success":
        flash(res["message"], "success")
    else:
        flash(res["message"], "danger")
    return redirect(request.referrer or url_for("payslips.dashboard"))

@payslips_bp.route("/regenerate/<payslip_id>", methods=["POST"])
@hr_required
def regenerate_draft(payslip_id):
    user = session["user"]["employee_id"]
    res = payslip_service.regenerate_draft_payslip(payslip_id, user)
    if res["status"] == "success":
        flash(res["message"], "success")
    else:
        flash(res["message"], "danger")
    return redirect(request.referrer or url_for("payslips.dashboard"))

@payslips_bp.route("/cancel/<payslip_id>", methods=["POST"])
@hr_required
def cancel_draft(payslip_id):
    user = session["user"]["employee_id"]
    res = payslip_service.cancel_draft_payslip(payslip_id, user)
    if res["status"] == "success":
        flash(res["message"], "success")
    else:
        flash(res["message"], "danger")
    return redirect(request.referrer or url_for("payslips.dashboard"))
