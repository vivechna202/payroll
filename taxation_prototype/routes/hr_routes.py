"""
hr_routes.py – All routes accessible to the HR role.

Pages:
  /hr/payroll-processing  → payroll_processing.html
  /hr/monthly-tds         → monthly_tds.html
  /hr/proof-approval      → proof_approval.html
  /hr/declaration-window  → declaration_window.html
  /hr/form24q             → form24q.html
"""

from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from functools import wraps
import io
from datetime import date
from config import CSV_DECLARATION_WINDOWS, CSV_EMPLOYEES, CURRENT_FY
from services.csv_service import csv_to_records, append_row, get_all_declarations
from services.payroll_service import get_all_payroll_records, process_monthly_payroll, get_payroll_summary, get_all_employee_salaries, get_employee_salary, update_employee_salary
from services.tax_service import get_monthly_tds_records, compute_tds_for_month
from services.proof_service import get_all_proofs, get_all_pending_proofs, approve_proof, reject_proof
from services.form24q_service import get_quarterly_summary, get_form24q_files, generate_form24q, get_quarterly_employee_details, get_fvu_path, save_fvu_path, run_fvu_validation
from services.payroll_register_service import get_payroll_register_data, get_register_dashboard_stats, export_to_excel, export_to_csv, get_unique_departments
from flask import send_file, Response

hr_bp = Blueprint("hr", __name__, url_prefix="/hr")


# ─────────────────────────────────────────────────────────────
# Auth guard
# ─────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

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
        
        # TDS regime and deduction fields
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

@hr_bp.route("/monthly-tds", methods=["GET", "POST"])
@hr_required
def monthly_tds():
    user = session["user"]
    today = date.today()
    month = request.args.get("month", str(today.month))
    fy = request.args.get("fy", CURRENT_FY)
    
    if request.method == "POST":
        result = compute_tds_for_month(
            request.form.get("month", month),
            request.form.get("fy", fy)
        )
        if result["status"] == "success":
            flash(f"TDS Calculation triggered. {result['message']}", "success")
        else:
            flash(result["message"], "danger")
        return redirect(url_for("hr.monthly_tds", month=month, fy=fy))

    tds_records = get_monthly_tds_records(month, fy)
    employees = get_all_employee_salaries()
    
    return render_template(
        "hr/monthly_tds.html",
        user=user,
        tds_records=tds_records,
        employees=employees,
        selected_month=month,
        fy=fy,
        active_page="monthly_tds",
    )


@hr_bp.route("/proof-approval", methods=["GET", "POST"])
@hr_required
def proof_approval():
    user = session["user"]

    if request.method == "POST":
        proof_id = request.form.get("proof_id")
        action = request.form.get("action")
        remarks = request.form.get("remarks", "")
        if action == "approve":
            approve_proof(proof_id, user["name"], remarks)
            flash(f"Proof {proof_id} approved.", "success")
        elif action == "reject":
            reject_proof(proof_id, user["name"], remarks)
            flash(f"Proof {proof_id} rejected.", "warning")
        return redirect(url_for("hr.proof_approval"))

    filter_status = request.args.get("status", "ALL")
    filter_employee = request.args.get("employee_id", "").strip().lower()
    
    if filter_status == "PENDING":
        proofs = get_all_pending_proofs()
    elif filter_status != "ALL":
        all_proofs = get_all_proofs()
        proofs = [p for p in all_proofs if p.get("status") == filter_status]
    else:
        proofs = get_all_proofs()
        
    if filter_employee:
        proofs = [p for p in proofs if filter_employee in p.get("employee_id", "").lower()]

    return render_template(
        "hr/proof_approval.html",
        user=user,
        proofs=proofs,
        filter_status=filter_status,
        filter_employee=request.args.get("employee_id", ""),
        active_page="proof_approval",
    )


@hr_bp.route("/declaration-window", methods=["GET", "POST"])
@hr_required
def declaration_window():
    user = session["user"]
    windows = csv_to_records(CSV_DECLARATION_WINDOWS)

    if request.method == "POST":
        import uuid
        new_window = {
            "window_id": str(uuid.uuid4())[:8].upper(),
            "fy": request.form.get("fy", CURRENT_FY),
            "window_type": request.form.get("window_type", ""),
            "start_date": request.form.get("start_date", ""),
            "end_date": request.form.get("end_date", ""),
            "created_by": user["name"],
            "created_on": date.today().isoformat(),
            "status": "ACTIVE",
        }
        append_row(CSV_DECLARATION_WINDOWS, new_window)
        flash("Declaration window created successfully.", "success")
        return redirect(url_for("hr.declaration_window"))

    return render_template(
        "hr/declaration_window.html",
        user=user,
        windows=windows,
        fy=CURRENT_FY,
        active_page="declaration_window",
    )


@hr_bp.route("/declarations")
@hr_required
def declarations():
    user = session["user"]
    all_declarations = get_all_declarations()
    
    emp_filter = request.args.get("employee_id", "").strip().lower()
    fy_filter = request.args.get("fy", "")
    status_filter = request.args.get("status", "")
    
    filtered_declarations = []
    for d in all_declarations:
        if emp_filter and emp_filter not in d.get("employee_id", "").lower():
            continue
        if fy_filter and d.get("financial_year") != fy_filter:
            continue
        if status_filter and d.get("status") != status_filter:
            continue
        filtered_declarations.append(d)
        
    return render_template(
        "hr/declarations_view.html",
        user=user,
        declarations=filtered_declarations,
        fy=CURRENT_FY,
        active_page="hr_declarations",
    )


@hr_bp.route("/form24q", methods=["GET", "POST"])
@hr_required
def form24q():
    user = session["user"]
    selected_quarter = request.args.get("quarter", "Q1")
    selected_fy = request.args.get("fy", CURRENT_FY)

    quarterly_summary = get_quarterly_summary(selected_quarter, selected_fy)
    employee_details = get_quarterly_employee_details(selected_quarter, selected_fy)
    generated_files = get_form24q_files(selected_fy)
    fvu_path = get_fvu_path()

    if request.method == "POST":
        quarter = request.form.get("quarter", selected_quarter)
        fy = request.form.get("fy", selected_fy)
        print(f"[ROUTE] POST /hr/form24q — quarter={quarter}, fy={fy}, user={user['name']}")
        print("[ROUTE] Calling generate_form24q (TXT only, no FVU)...")
        result = generate_form24q(quarter, fy, user["name"])
        print(f"[ROUTE] generate_form24q returned: status={result.get('status')}, message={result.get('message')}")
        if result.get("status") == "success":
            flash(result.get("message"), "success")
        else:
            flash(result.get("message"), "danger")
        return redirect(url_for("hr.form24q", quarter=quarter, fy=fy))

    return render_template(
        "hr/form24q.html",
        user=user,
        quarterly_summary=quarterly_summary,
        employee_details=employee_details,
        generated_files=generated_files,
        selected_quarter=selected_quarter,
        selected_fy=selected_fy,
        fvu_path=fvu_path,
        fy=CURRENT_FY,
        active_page="form24q",
    )


@hr_bp.route("/form24q/config-fvu", methods=["POST"])
@hr_required
def config_fvu():
    fvu_path = request.form.get("fvu_path", "").strip()
    save_fvu_path(fvu_path)
    flash("Government FVU Utility path configuration updated successfully.", "success")
    return redirect(url_for("hr.form24q"))


@hr_bp.route("/form24q/run-fvu", methods=["POST"])
@hr_required
def run_fvu():
    import os
    from werkzeug.utils import secure_filename
    from config import FORM24Q_FOLDER, CSI_FOLDER

    user = session["user"]
    print(f"[ROUTE] POST /hr/form24q/run-fvu — user={user['name']}")

    txt_file = request.files.get("txt_file")
    csi_file = request.files.get("csi_file")

    if not txt_file or txt_file.filename == "":
        flash("Form 24Q TXT file is required to run FVU validation.", "danger")
        return redirect(url_for("hr.form24q"))

    if not csi_file or csi_file.filename == "":
        flash("CSI file is required to run FVU validation.", "danger")
        return redirect(url_for("hr.form24q"))

    # Save uploaded TXT into the FORM24Q_FOLDER
    os.makedirs(FORM24Q_FOLDER, exist_ok=True)
    txt_filename = secure_filename(txt_file.filename)
    txt_filepath = os.path.join(FORM24Q_FOLDER, txt_filename)
    txt_file.save(txt_filepath)
    print(f"[ROUTE] TXT file saved: {txt_filepath}")

    # Save uploaded CSI into the CSI_FOLDER
    os.makedirs(CSI_FOLDER, exist_ok=True)
    csi_filename = secure_filename(csi_file.filename)
    csi_filepath = os.path.join(CSI_FOLDER, csi_filename)
    csi_file.save(csi_filepath)
    print(f"[ROUTE] CSI file saved: {csi_filepath}")

    print("[ROUTE] Calling run_fvu_validation service...")
    result = run_fvu_validation(txt_filepath, csi_filepath, user["name"])
    print(f"[ROUTE] run_fvu_validation returned: status={result.get('status')}, message={result.get('message')}")

    if result.get("status") == "success":
        flash(result.get("message"), "success")
    else:
        flash(result.get("message"), "danger")
    return redirect(url_for("hr.form24q"))


@hr_bp.route("/form24q/download/<filename>")
@hr_required
def download_form24q(filename):
    import os
    from flask import send_from_directory
    from config import FORM24Q_FOLDER
    file_path = os.path.join(FORM24Q_FOLDER, filename)
    if not os.path.exists(file_path):
        flash("File not found.", "danger")
        return redirect(url_for("hr.form24q"))
    return send_from_directory(FORM24Q_FOLDER, filename, as_attachment=True)


@hr_bp.route("/form16", methods=["GET"])
@hr_required
def form16():
    user = session["user"]
    selected_fy = request.args.get("fy", CURRENT_FY)
    
    from services.form16_service import get_eligible_employees, get_form16_history
    eligible_employees = get_eligible_employees(selected_fy)
    history = get_form16_history(selected_fy)
    
    generated_employee_ids = [h.get("employee_id") for h in history]
    
    return render_template(
        "hr/form16.html",
        user=user,
        eligible_employees=eligible_employees,
        history=history,
        generated_employee_ids=generated_employee_ids,
        selected_fy=selected_fy,
        active_page="form16",
    )


@hr_bp.route("/form16/single", methods=["POST"])
@hr_required
def form16_single():
    user = session["user"]
    employee_id = request.form.get("employee_id")
    fy = request.form.get("fy", CURRENT_FY)
    
    from services.form16_service import generate_form16
    res = generate_form16(employee_id, fy, user["name"])
    if res.get("status") == "success":
        flash(res.get("message"), "success")
    else:
        flash(res.get("message"), "danger")
    return redirect(url_for("hr.form16", fy=fy))


@hr_bp.route("/form16/bulk", methods=["POST"])
@hr_required
def form16_bulk():
    user = session["user"]
    fy = request.form.get("fy", CURRENT_FY)
    
    from services.form16_service import bulk_generate_form16
    res = bulk_generate_form16(fy, user["name"])
    if res.get("status") == "success":
        flash(res.get("message"), "success")
    else:
        flash(res.get("message"), "danger")
    return redirect(url_for("hr.form16", fy=fy))


@hr_bp.route("/challan-details")
@hr_required
def challan_details():
    return render_template("hr/challan_details.html", active_page="challan_details")


@hr_bp.route("/challans/list")
@hr_required
def challans_list():
    from services.challan_service import get_all_challans
    from flask import jsonify, make_response
    try:
        challans = get_all_challans()
        response = make_response(jsonify(challans))
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@hr_bp.route("/challans/add", methods=["POST"])
@hr_required
def challans_add():
    from services.challan_service import save_challan
    from flask import jsonify, request
    try:
        data = request.get_json() or {}
        result = save_challan(data)
        status_code = 200 if result.get("status") == "success" else 400
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@hr_bp.route("/challans/update/<challan_id>", methods=["POST", "PUT"])
@hr_required
def challans_update(challan_id):
    from services.challan_service import edit_challan
    from flask import jsonify, request
    try:
        data = request.get_json() or {}
        result = edit_challan(challan_id, data)
        status_code = 200 if result.get("status") == "success" else 400
        return jsonify(result), status_code
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@hr_bp.route("/challans/delete/<challan_id>", methods=["POST", "DELETE"])
@hr_required
def challans_delete(challan_id):
    from services.challan_service import delete_challan
    from flask import jsonify
    try:
        success = delete_challan(challan_id)
        if success:
            return jsonify({"status": "success", "message": "Challan deleted successfully"})
        else:
            return jsonify({"status": "error", "message": "Challan not found or delete failed"}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
