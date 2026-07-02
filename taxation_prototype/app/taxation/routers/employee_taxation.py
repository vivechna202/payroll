"""Employee taxation routes."""
from fastapi import Request

from app.base.utils.flask_compat import render_template, session, redirect, url_for, flash, send_from_directory, send_file, abort
import os
import csv
from app.base.utils.config import CSV_EMPLOYEES, CSV_DECLARATIONS, CSV_FORM16_HISTORY, CURRENT_FY, CSV_FORM16_APPROVED, FORM16_FOLDER, FORM16_SIGNED_FOLDER
from app.base.utils.csv_service import (
    read_csv_row, csv_to_records, create_declaration, update_declaration,
    get_employee_declarations, get_declaration_items, is_declaration_window_open,
)
from app.taxation.services.tax_service import get_employee_tax_summary, get_tax_regime_comparison
from app.taxation.services.proof_service import get_proofs_for_employee, submit_proof, allowed_file
from app.payroll.services.payroll_service import get_employee_payroll
from app.base.routers.blueprints import employee_bp, employee_required

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
async def investment_declaration(request: Request):
    user = session["user"]
    fy = request.query_params.get("fy", CURRENT_FY)
    
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
            
        form = await request.form()
        action = form.get("action", "DRAFT")
        status = "SUBMITTED" if action == "SUBMIT" else "DRAFT"
        regime = form.get("tax_regime", "OLD")
        
        items = {}
        for key, value in form.items():
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
async def proof_upload(request: Request):
    user = session["user"]
    proofs = get_proofs_for_employee(user["employee_id"])
    
    declarations = get_employee_declarations(user["employee_id"])
    submitted_declarations = [d for d in declarations if d.get("status") == "SUBMITTED"]

    if request.method == "POST":
        form = await request.form()
        section = form.get("section")
        declaration_id = form.get("declaration_id")
        
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
async def form16_download(request: Request):
    user = session["user"]
    fy = request.query_params.get("fy", CURRENT_FY)
    
    from app.taxation.services.form16_service import get_form16_history, get_form16_details
    form16_records = get_form16_history(fy=fy, employee_id=user["employee_id"])
    form16_details = get_form16_details(user["employee_id"], fy)
    
    # Get published Form16 PDFs from CSV (persisted by HR)
    import os
    import csv
    from app.base.utils.config import CSV_FORM16_APPROVED
    from app.base.utils.csv_service import read_csv_row
    
    published_form16s = []
    if os.path.exists(CSV_FORM16_APPROVED):
        with open(CSV_FORM16_APPROVED, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                employee_data = read_csv_row(CSV_EMPLOYEES, "employee_id", user["employee_id"])
                if employee_data and row.get("pan") == employee_data.get("pan") and row.get("published") == "True":
                    published_form16s.append(row)
    
    return render_template(
        "employee/form16_download.html",
        user=user,
        form16_records=form16_records,
        form16_details=form16_details,
        published_form16s=published_form16s,
        fy=fy,
        active_page="form16_download",
    )


@employee_bp.route("/form16/download/<filename>")
@employee_required
def download_form16(filename):
    import os
    from app.base.utils.flask_compat import send_from_directory, abort
    from app.base.utils.config import FORM16_FOLDER
    
    user = session["user"]
    from app.taxation.services.form16_service import get_form16_history
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


@employee_bp.route("/form16/download-approved/<filename>")
@employee_required
def download_approved_form16(filename):
    """
    Download an approved Form16 PDF (merged, signed, and approved by HR).
    Only accessible to the employee whose PAN matches the approval record.
    """
    import os
    from app.base.utils.flask_compat import send_file, abort, flash, redirect, url_for
    from app.base.utils.config import FORM16_SIGNED_FOLDER
    from app.base.utils.csv_service import read_csv_row
    
    user = session["user"]
    
    # Get employee PAN
    employee_data = read_csv_row(CSV_EMPLOYEES, "employee_id", user["employee_id"])
    if not employee_data:
        print("[DEBUG] Employee data not found for ID:", user["employee_id"])
        abort(403)
    
    employee_pan = employee_data.get("pan")
    
    # Check if this file is published for this employee
    from app.base.utils.config import CSV_FORM16_APPROVED
    import csv
    
    published_record = None
    if os.path.exists(CSV_FORM16_APPROVED):
        with open(CSV_FORM16_APPROVED, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Find all matching records and get the most recent one by published_at
            matching_records = []
            for row in reader:
                if row.get("filename") == filename and row.get("pan") == employee_pan and row.get("published") == "True":
                    matching_records.append(row)
            
            if matching_records:
                # Sort by published_at (most recent first)
                matching_records.sort(key=lambda x: x.get("published_at", ""), reverse=True)
                published_record = matching_records[0]
                print(f"[DEBUG] Found {len(matching_records)} matching records, using most recent from: {published_record.get('published_at')}")
    
    if not published_record:
        print(f"[DEBUG] No published record found in CSV ({CSV_FORM16_APPROVED}) for filename={filename}, pan={employee_pan}")
        abort(403)
    
    # Get session_id from published record for exact path lookup
    session_id = published_record.get("session_id")
    
    # Construct exact path using session_id (no fallback search)
    file_path = None
    if session_id:
        file_path = os.path.join(FORM16_SIGNED_FOLDER, session_id, filename)
        print(f"[DEBUG] Using session_id from CSV: {session_id}")
        print(f"[DEBUG] Constructed path: {file_path}")
    else:
        print(f"[ERROR] No session_id in CSV - cannot determine exact file path")
        flash("Form 16 record is missing session information. Please contact HR.", "danger")
        return redirect(url_for("employee.form16_download"))
    
    # Debug logs requested:
    # * Stored path (from config/database)
    # * Download path
    # * File exists
    # * File size
    stored_path_log = f"CSV: {CSV_FORM16_APPROVED}, session_id: {session_id}"
    download_path_log = file_path if file_path else "Not found in signed folder"
    file_exists_log = os.path.exists(file_path) if file_path else False
    file_size_log = os.path.getsize(file_path) if (file_path and file_exists_log) else 0
    
    print(f"[DEBUG] Stored path: {stored_path_log}")
    print(f"[DEBUG] Download path: {download_path_log}")
    print(f"[DEBUG] File exists: {file_exists_log}")
    print(f"[DEBUG] File size: {file_size_log} bytes")
    
    # Strict validation of existence and size
    if not file_path or not file_exists_log:
        print(f"[ERROR] Signed PDF not found at: {file_path}")
        flash("Signed Form 16 PDF not found on the server. Please contact HR.", "danger")
        return redirect(url_for("employee.form16_download"))
        
    if file_size_log == 0:
        print(f"[ERROR] Signed PDF is empty (0 bytes) at: {file_path}")
        flash("The signed Form 16 PDF is empty. Please contact HR to regenerate and re-sign.", "danger")
        return redirect(url_for("employee.form16_download"))
        
    return send_file(file_path, as_attachment=True, download_name=filename, mimetype="application/pdf")


