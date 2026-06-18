"""
employee_routes.py – All routes accessible to the Employee role.

Pages:
  /employee/tax-dashboard          → tax_dashboard.html
  /employee/investment-declaration → investment_declaration.html
  /employee/proof-upload           → proof_upload.html
  /employee/form16-download        → form16_download.html
"""

from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from functools import wraps
from config import CSV_EMPLOYEES, CSV_DECLARATIONS, CSV_FORM16_HISTORY, CURRENT_FY
from services.csv_service import (
    read_csv_row, csv_to_records, create_declaration, update_declaration, 
    get_employee_declarations, get_declaration_items, is_declaration_window_open
)
from services.tax_service import get_employee_tax_summary, get_tax_regime_comparison, get_tax_regime_comparison
from services.proof_service import get_proofs_for_employee, submit_proof, allowed_file
from services.payroll_service import get_employee_payroll

employee_bp = Blueprint("employee", __name__, url_prefix="/employee")


# ─────────────────────────────────────────────────────────────
# Auth guard
# ─────────────────────────────────────────────────────────────

def employee_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        if session["user"].get("role") not in ("employee", "hr"):
            flash("Access denied.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@employee_bp.route("/tax-dashboard")
@employee_required
def tax_dashboard():
    user = session["user"]
    tax_summary = get_employee_tax_summary(user["employee_id"], CURRENT_FY)
    regime_comparison = get_tax_regime_comparison(user["employee_id"], CURRENT_FY)
    payroll_history = get_employee_payroll(user["employee_id"])
    return render_template(
        "employee/tax_dashboard.html",
        user=user,
        tax_summary=tax_summary,
        regime_comparison=regime_comparison,
        payroll_history=payroll_history,
        fy=CURRENT_FY,
        active_page="tax_dashboard",
    )


@employee_bp.route("/investment-declaration", methods=["GET", "POST"])
@employee_required
def investment_declaration():
    user = session["user"]
    fy = request.args.get("fy", CURRENT_FY)
    
    declarations = get_employee_declarations(user["employee_id"])
    fy_declarations = [d for d in declarations if d.get("financial_year") == fy]
    existing_declaration = fy_declarations[-1] if fy_declarations else None
    
    declaration_items = {}
    if existing_declaration:
        declaration_items = get_declaration_items(existing_declaration["declaration_id"])
        
    window_open = is_declaration_window_open(fy)

    if request.method == "POST":
        if not window_open:
            flash(f"Declaration window for FY {fy} is closed.", "danger")
            return redirect(url_for("employee.investment_declaration", fy=fy))
            
        if existing_declaration and existing_declaration.get("status") == "SUBMITTED":
            flash("Cannot edit a submitted declaration.", "danger")
            return redirect(url_for("employee.investment_declaration", fy=fy))
            
        action = request.form.get("action", "DRAFT")
        status = "SUBMITTED" if action == "SUBMIT" else "DRAFT"
        regime = request.form.get("tax_regime", "OLD")
        
        items = {}
        for key, value in request.form.items():
            if key not in ["action", "tax_regime"] and value.strip():
                items[key] = value.strip()
                
        if existing_declaration:
            update_declaration(existing_declaration["declaration_id"], regime, items, status)
            flash(f"Declaration updated as {status}.", "success")
        else:
            create_declaration(user["employee_id"], fy, regime, items, status)
            flash(f"Declaration created as {status}.", "success")
            
        return redirect(url_for("employee.investment_declaration", fy=fy))

    return render_template(
        "employee/investment_declaration.html",
        user=user,
        declarations=declarations,
        existing_declaration=existing_declaration,
        declaration_items=declaration_items,
        window_open=window_open,
        fy=fy,
        active_page="investment_declaration",
    )


@employee_bp.route("/proof-upload", methods=["GET", "POST"])
@employee_required
def proof_upload():
    user = session["user"]
    proofs = get_proofs_for_employee(user["employee_id"])
    
    declarations = get_employee_declarations(user["employee_id"])
    submitted_declarations = [d for d in declarations if d.get("status") == "SUBMITTED"]

    if request.method == "POST":
        section = request.form.get("section")
        declaration_id = request.form.get("declaration_id")
        
        decl = next((d for d in submitted_declarations if d.get("declaration_id") == declaration_id), None)
        if not decl:
            flash("Invalid or unsubmitted declaration ID.", "danger")
            return redirect(url_for("employee.proof_upload"))
            
        if "proof_file" not in request.files:
            flash("No file uploaded.", "danger")
            return redirect(url_for("employee.proof_upload"))
            
        file_obj = request.files["proof_file"]
        if file_obj.filename == "":
            flash("No selected file.", "danger")
            return redirect(url_for("employee.proof_upload"))
            
        if not allowed_file(file_obj.filename):
            flash("Invalid file type. Allowed: PDF, PNG, JPG, JPEG.", "danger")
            return redirect(url_for("employee.proof_upload"))
            
        submit_proof(user["employee_id"], declaration_id, section, file_obj)
        flash("Proof uploaded successfully.", "success")
        return redirect(url_for("employee.proof_upload"))

    return render_template(
        "employee/proof_upload.html",
        user=user,
        proofs=proofs,
        submitted_declarations=submitted_declarations,
        active_page="proof_upload",
    )


@employee_bp.route("/form16-download")
@employee_required
def form16_download():
    user = session["user"]
    fy = request.args.get("fy", CURRENT_FY)
    
    from services.form16_service import get_form16_history, get_form16_details
    form16_records = get_form16_history(fy=fy, employee_id=user["employee_id"])
    form16_details = get_form16_details(user["employee_id"], fy)
    
    return render_template(
        "employee/form16_download.html",
        user=user,
        form16_records=form16_records,
        form16_details=form16_details,
        fy=fy,
        active_page="form16_download",
    )


@employee_bp.route("/form16/download/<filename>")
@employee_required
def download_form16(filename):
    import os
    from flask import send_from_directory, abort
    from config import FORM16_FOLDER
    
    user = session["user"]
    from services.form16_service import get_form16_history
    history = get_form16_history()
    record = next((r for r in history if r.get("file_name") == filename), None)
    
    if not record:
        abort(404)
        
    if user["role"] == "employee" and record.get("employee_id") != user["employee_id"]:
        abort(403)
        
    file_path = os.path.join(FORM16_FOLDER, filename)
    if not os.path.exists(file_path):
        abort(404)
        
    return send_from_directory(FORM16_FOLDER, filename, as_attachment=True)
