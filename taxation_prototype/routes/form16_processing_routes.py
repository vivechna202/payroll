"""
form16_processing_routes.py
────────────────────────────────────────────────────────────
HR-only blueprint for the Form 16 Processing module.

URL prefix: /hr/form16-processing

All routes are guarded by hr_required (role == 'hr').
TAN is stored ONLY in session['f16p_tan'] — never written anywhere.

Routes:
  GET  /               → Dashboard (TAN input + upload + results)
  POST /set-tan        → Validate & store TAN in session
  POST /clear-tan      → Remove TAN from session
  POST /upload         → Bulk PDF/ZIP upload + decrypt + extract
  GET  /results        → Reload dashboard with current session data
  POST /clear-session  → Wipe all session processing data + temp files
  GET  /download-log   → Download processing event log CSV (audit)
"""

import os
import uuid
import csv
from datetime import datetime

from flask import (
    Blueprint, render_template, session, redirect, url_for,
    flash, request, jsonify, send_file, abort
)
from functools import wraps

from config import (
    CURRENT_FY, CSV_FORM16_PROCESSING_LOG, CSV_FORM16_APPROVED, FORM16_PROCESSING_FOLDER
)
from services.form16_processing_service import (
    validate_tan,
    process_uploaded_files,
    get_dashboard_data,
    cleanup_session_files,
    load_session_results,
    match_parts,
    # ── Task 2: Merge Engine ──
    bulk_merge_session,
    get_merge_dashboard_data,
    load_merge_results,
    zip_merged_files,
)

# ─────────────────────────────────────────────────────────────
# Blueprint
# ─────────────────────────────────────────────────────────────

form16_processing_bp = Blueprint(
    "form16_processing", __name__, url_prefix="/hr/form16-processing"
)


@form16_processing_bp.before_request
def _raise_upload_limit():
    """Allow up to 50 MB uploads for Form 16 Processing (global limit is 5 MB)."""
    from flask import current_app
    current_app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024


@form16_processing_bp.after_request
def _restore_upload_limit(response):
    """Restore the global 5 MB limit after processing the request."""
    from flask import current_app
    current_app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024
    return response

# ─────────────────────────────────────────────────────────────
# Auth guard (HR-only) — mirrors hr_routes.py, not imported to
# avoid circular imports but uses identical logic.
# ─────────────────────────────────────────────────────────────

def hr_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        if session["user"].get("role") != "hr":
            flash("Access denied. This section is for HR personnel only.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


# ─────────────────────────────────────────────────────────────
# Session key constants
# ─────────────────────────────────────────────────────────────

SESSION_TAN_KEY        = "f16p_tan"           # Stores TAN string (RAM only)
SESSION_ID_KEY         = "f16p_session_id"    # Stores processing session UUID
SESSION_PROCESSED_KEY  = "f16p_has_results"   # Bool — results exist for this session
SESSION_MERGED_KEY     = "f16p_has_merge"     # Bool — merge results exist for this session
SESSION_APPROVED_KEY    = "f16p_approved"      # List of approved Form16 records
SESSION_PUBLISHED_KEY   = "f16p_published"     # List of published Form16 records


# ─────────────────────────────────────────────────────────────
# Helper: get or create processing session ID
# ─────────────────────────────────────────────────────────────

def _get_or_create_session_id() -> str:
    if SESSION_ID_KEY not in session:
        session[SESSION_ID_KEY] = str(uuid.uuid4()).replace("-", "")[:16].upper()
    return session[SESSION_ID_KEY]


# ─────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────

@form16_processing_bp.route("/", methods=["GET"])
@hr_required
def dashboard():
    """
    Main dashboard page.
    Shows TAN input, upload form (if TAN set), results (if processed),
    and merge dashboard (if merge has been run).
    """
    user = session["user"]
    tan_set = SESSION_TAN_KEY in session and bool(session[SESSION_TAN_KEY])
    processing_session_id = session.get(SESSION_ID_KEY)
    has_results = session.get(SESSION_PROCESSED_KEY, False)
    has_merge   = session.get(SESSION_MERGED_KEY, False)
    approved_count = len(session.get(SESSION_APPROVED_KEY, []))
    published_count = len(session.get(SESSION_PUBLISHED_KEY, []))

    dashboard_data = None
    if has_results and processing_session_id:
        try:
            dashboard_data = get_dashboard_data(processing_session_id)
        except Exception:
            has_results = False

    merge_data = None
    if processing_session_id:
        try:
            merge_data = get_merge_dashboard_data(processing_session_id)
            if not merge_data.get("has_merge_results"):
                merge_data = None
        except Exception:
            merge_data = None

    return render_template(
        "hr/form16_processing.html",
        user=user,
        tan_set=tan_set,
        has_results=has_results,
        has_merge=has_merge,
        dashboard_data=dashboard_data,
        merge_data=merge_data,
        approved_count=approved_count,
        published_count=published_count,
        fy=CURRENT_FY,
        active_page="form16_processing",
    )



@form16_processing_bp.route("/set-tan", methods=["POST"])
@hr_required
def set_tan():
    """Validate TAN and store in session (never persisted elsewhere)."""
    tan_input = request.form.get("tan", "").strip().upper()
    result = validate_tan(tan_input)

    if not result["valid"]:
        flash(f"TAN validation failed: {result['message']}", "danger")
        return redirect(url_for("form16_processing.dashboard"))

    # Store only in session (in-memory, not written to any file)
    session[SESSION_TAN_KEY] = tan_input
    # Reset any previous processing session
    _reset_processing_session()
    flash(f"TAN accepted and stored for this session only. You may now upload PDFs.", "success")
    return redirect(url_for("form16_processing.dashboard"))


@form16_processing_bp.route("/clear-tan", methods=["POST"])
@hr_required
def clear_tan():
    """Remove TAN from session and clean up processing data."""
    _full_session_clear()
    flash("TAN cleared. All processing data for this session has been wiped.", "info")
    return redirect(url_for("form16_processing.dashboard"))


@form16_processing_bp.route("/upload", methods=["POST"])
@hr_required
def upload():
    """
    Handle bulk PDF / ZIP upload.
    Decrypts using session TAN (never reads TAN from request body).
    Extracts metadata and stores results in session-scoped JSON.
    """
    # TAN must be set in session
    tan = session.get(SESSION_TAN_KEY)
    if not tan:
        flash("No TAN found in session. Please enter your TAN before uploading.", "warning")
        return redirect(url_for("form16_processing.dashboard"))

    # Get uploaded files
    files = request.files.getlist("pdf_files")
    if not files or all(f.filename == "" for f in files):
        flash("No files selected. Please choose PDF files or a ZIP archive.", "warning")
        return redirect(url_for("form16_processing.dashboard"))

    # Validate total upload size (guard against exceeding 50 MB)
    total_size = sum(
        f.content_length or 0 for f in files
        if hasattr(f, 'content_length') and f.content_length
    )

    processing_session_id = _get_or_create_session_id()

    try:
        # Process: decrypt + extract. TAN is passed as a function arg, not stored.
        result = process_uploaded_files(files, tan, processing_session_id)
    except Exception as e:
        flash(f"An unexpected error occurred during processing: {str(e)}", "danger")
        return redirect(url_for("form16_processing.dashboard"))

    summary = result.get("summary", {})
    total   = summary.get("total", 0)
    dec_ok  = summary.get("decrypted", 0)
    failed  = summary.get("failed", 0)

    if total == 0:
        flash("No valid PDF files were found in your upload.", "warning")
    else:
        if dec_ok > 0:
            flash(
                f"Processing complete: {total} file(s) uploaded, "
                f"{dec_ok} decrypted successfully, {failed} failed.",
                "success" if failed == 0 else "warning"
            )
        else:
            flash(
                f"Decryption failed for all {total} file(s). "
                "Please verify the TAN matches the PDF password.",
                "danger"
            )

    session[SESSION_PROCESSED_KEY] = total > 0
    return redirect(url_for("form16_processing.dashboard"))


@form16_processing_bp.route("/results", methods=["GET"])
@hr_required
def results():
    """Explicit results reload (same as dashboard)."""
    return redirect(url_for("form16_processing.dashboard"))


@form16_processing_bp.route("/clear-session", methods=["POST"])
@hr_required
def clear_session_data():
    """Wipe all session processing data and temp files."""
    _full_session_clear()
    flash("Processing session cleared. All temporary files have been removed.", "info")
    return redirect(url_for("form16_processing.dashboard"))


@form16_processing_bp.route("/download-log", methods=["GET"])
@hr_required
def download_log():
    """Download the processing audit log CSV (TAN-free)."""
    if not os.path.exists(CSV_FORM16_PROCESSING_LOG):
        flash("No processing log found yet.", "warning")
        return redirect(url_for("form16_processing.dashboard"))
    return send_file(
        CSV_FORM16_PROCESSING_LOG,
        as_attachment=True,
        download_name="form16_processing_audit_log.csv",
        mimetype="text/csv"
    )


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _reset_processing_session():
    """Clear processing results but keep TAN."""
    old_id = session.pop(SESSION_ID_KEY, None)
    session.pop(SESSION_PROCESSED_KEY, None)
    session.pop(SESSION_MERGED_KEY, None)
    session.pop(SESSION_APPROVED_KEY, None)
    session.pop(SESSION_PUBLISHED_KEY, None)
    if old_id:
        cleanup_session_files(old_id)


def _full_session_clear():
    """Remove TAN + all processing session data from session and disk."""
    session.pop(SESSION_TAN_KEY, None)
    old_id = session.pop(SESSION_ID_KEY, None)
    session.pop(SESSION_PROCESSED_KEY, None)
    session.pop(SESSION_MERGED_KEY, None)
    session.pop(SESSION_APPROVED_KEY, None)
    session.pop(SESSION_PUBLISHED_KEY, None)
    if old_id:
        cleanup_session_files(old_id)


# ═════════════════════════════════════════════════════════════
# TASK 2 — PDF MERGE ROUTES
# All routes use the same hr_required guard.
# No TAN needed — merges already-decrypted files from Task 1.
# Additional routes:
#   POST /merge          → Run bulk merge for all Ready records
#   GET  /merge/download/<filename>  → Download one merged PDF
#   GET  /merge/download-all         → Download all merged PDFs as ZIP
# ═════════════════════════════════════════════════════════════


@form16_processing_bp.route("/merge", methods=["POST"])
@hr_required
def run_merge():
    """
    Trigger bulk PDF merge for all Ready records in the current session.
    Reads already-decrypted files from Task 1 — no TAN required.
    """
    processing_session_id = session.get(SESSION_ID_KEY)
    if not processing_session_id:
        flash("No processing session found. Please upload and process PDFs first.", "warning")
        return redirect(url_for("form16_processing.dashboard"))

    if not session.get(SESSION_PROCESSED_KEY):
        flash("No processed PDF data found. Complete the upload and extraction step first.", "warning")
        return redirect(url_for("form16_processing.dashboard"))

    try:
        result = bulk_merge_session(processing_session_id)
    except Exception as e:
        flash(f"Merge operation failed unexpectedly: {str(e)}", "danger")
        return redirect(url_for("form16_processing.dashboard"))

    summary = result.get("summary", {})
    merged  = summary.get("merged", 0)
    failed  = summary.get("failed", 0)
    ready   = summary.get("ready", 0)
    skipped = summary.get("skipped", 0)

    if ready == 0:
        flash(
            f"No Ready records found to merge. "
            f"{skipped} record(s) skipped (missing Part A or B).",
            "warning"
        )
    elif merged > 0:
        flash(
            f"Merge complete: {merged}/{ready} Form 16 PDF(s) generated successfully."
            + (f" {failed} failed." if failed else ""),
            "success" if failed == 0 else "warning"
        )
    else:
        flash(
            f"Merge failed for all {ready} record(s). Check that decrypted source files are intact.",
            "danger"
        )

    session[SESSION_MERGED_KEY] = merged > 0
    return redirect(url_for("form16_processing.dashboard"))


@form16_processing_bp.route("/merge/download/<path:filename>", methods=["GET"])
@hr_required
def download_merged(filename):
    """
    Download a single merged Form 16 PDF.
    Filename must belong to the current session's output folder.
    """
    from flask import send_from_directory
    from config import FORM16_MERGED_FOLDER

    processing_session_id = session.get(SESSION_ID_KEY)
    if not processing_session_id:
        flash("No active session. Please process PDFs first.", "warning")
        return redirect(url_for("form16_processing.dashboard"))

    # Security: only serve files from this session's output subfolder
    session_out = os.path.join(FORM16_MERGED_FOLDER, processing_session_id)
    safe_filename = os.path.basename(filename)  # strip any path traversal
    target = os.path.join(session_out, safe_filename)

    if not os.path.exists(target):
        flash(f"File '{safe_filename}' not found. It may have been cleared.", "danger")
        return redirect(url_for("form16_processing.dashboard"))

    return send_file(
        target,
        as_attachment=True,
        download_name=safe_filename,
        mimetype="application/pdf"
    )


@form16_processing_bp.route("/merge/download-all", methods=["GET"])
@hr_required
def download_all_merged():
    """
    Package all successfully merged PDFs into a ZIP and stream it.
    """
    processing_session_id = session.get(SESSION_ID_KEY)
    if not processing_session_id:
        flash("No active session.", "warning")
        return redirect(url_for("form16_processing.dashboard"))

    result = zip_merged_files(processing_session_id)
    if not result["success"]:
        flash(f"ZIP creation failed: {result['error']}", "danger")
        return redirect(url_for("form16_processing.dashboard"))

    return send_file(
        result["zip_path"],
        as_attachment=True,
        download_name=os.path.basename(result["zip_path"]),
        mimetype="application/zip"
    )


# ═════════════════════════════════════════════════════════════
# TASK 4 — APPROVAL ROUTES
# Routes for HR to approve signed Form16 documents for distribution
# ═════════════════════════════════════════════════════════════


@form16_processing_bp.route("/approve", methods=["POST"])
@hr_required
def approve_form16():
    """
    Approve a signed Form16 document for employee distribution.
    Stores approval record in session and logs to audit CSV.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
        filename = data.get("filename")
        pan = data.get("pan")
        employee_name = data.get("employee_name")
        
        if not filename or not pan:
            return jsonify({"status": "error", "message": "filename and pan are required"}), 400
        
        # Initialize approved records list in session if not exists
        if SESSION_APPROVED_KEY not in session:
            session[SESSION_APPROVED_KEY] = []
        
        # Check if already approved
        approved_records = session[SESSION_APPROVED_KEY]
        for record in approved_records:
            if record.get("filename") == filename:
                return jsonify({"status": "error", "message": "Document already approved"}), 400
        
        # Verify signed PDF exists
        processing_session_id = session.get(SESSION_ID_KEY)
        if not processing_session_id:
            return jsonify({"status": "error", "message": "No processing session found"}), 400
            
        from config import FORM16_SIGNED_FOLDER
        session_signed_out = os.path.join(FORM16_SIGNED_FOLDER, processing_session_id)
        if not os.path.exists(os.path.join(session_signed_out, filename)):
            return jsonify({"status": "error", "message": "Signed PDF not found. Document must be signed before approval."}), 400
        
        # Create approval record
        approval_record = {
            "pan": pan,
            "employee_name": employee_name,
            "filename": filename,
            "approved_at": datetime.now().isoformat(),
            "approved_by": session["user"].get("username", "hr_user")
        }
        
        # Add to session
        session[SESSION_APPROVED_KEY].append(approval_record)
        session.modified = True
        
        # Persist to CSV for employee portal access
        _persist_approval_to_csv(approval_record)
        
        # Log to audit CSV
        _log_approval_to_csv(approval_record)
        
        return jsonify({"status": "success", "message": "Document approved successfully"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


def _persist_approval_to_csv(record):
    """
    Persist approved Form16 record to CSV for employee portal access.
    """
    try:
        file_exists = os.path.exists(CSV_FORM16_APPROVED)
        fieldnames = ["pan", "employee_name", "filename", "approved_at", "approved_by", "published", "published_by", "published_at"]
        write_header = not file_exists
        
        with open(CSV_FORM16_APPROVED, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            
            # Write header if file is new
            if write_header:
                writer.writeheader()
            
            writer.writerow({
                "pan": record.get("pan"),
                "employee_name": record.get("employee_name"),
                "filename": record.get("filename"),
                "approved_at": record.get("approved_at"),
                "approved_by": record.get("approved_by"),
                "published": "False",
                "published_by": "",
                "published_at": ""
            })
    except Exception as e:
        # Log error but don't fail the approval
        print(f"Error persisting approval to CSV: {e}")


def _log_approval_to_csv(record):
    """
    Log approval action to the Form16 processing audit CSV.
    """
    try:
        file_exists = os.path.exists(CSV_FORM16_PROCESSING_LOG)
        
        with open(CSV_FORM16_PROCESSING_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            
            # Write header if file is new
            if not file_exists:
                writer.writerow([
                    "timestamp", "action", "pan", "employee_name", 
                    "filename", "approved_by", "approved_at"
                ])
            
            writer.writerow([
                datetime.now().isoformat(),
                "APPROVE",
                record.get("pan"),
                record.get("employee_name"),
                record.get("filename"),
                record.get("approved_by"),
                record.get("approved_at")
            ])
    except Exception as e:
        # Log error but don't fail the approval
        print(f"Error logging approval to CSV: {e}")


# ═════════════════════════════════════════════════════════════
# TASK 5 — SIGNING & PUBLISH ROUTES
# ═════════════════════════════════════════════════════════════

@form16_processing_bp.route("/check-certificate", methods=["GET"])
@hr_required
def check_certificate():
    from services.sign_service import has_certificate
    return jsonify({"configured": has_certificate()})


@form16_processing_bp.route("/upload-certificate", methods=["POST"])
@hr_required
def upload_certificate():
    from services.sign_service import save_certificate
    if "certificate" not in request.files:
        return jsonify({"status": "error", "message": "No file uploaded"}), 400
        
    file_obj = request.files["certificate"]
    password = request.form.get("password")
    
    if not password:
        return jsonify({"status": "error", "message": "Password is required"}), 400
        
    try:
        save_certificate(file_obj)
        # Store password in session temporarily for this session's bulk signing if needed, 
        # or just return success and require password for each sign.
        # Actually, for bulk signing we usually ask once. 
        # The user's request: "Ask for certificate password. Proceed with signing flow."
        return jsonify({"status": "success", "message": "Certificate configured successfully"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@form16_processing_bp.route("/sign", methods=["POST"])
@hr_required
def sign_form16():
    """Sign the document cryptographically using pyHanko."""
    from services.sign_service import sign_pdf
    from config import FORM16_MERGED_FOLDER, FORM16_SIGNED_FOLDER
    
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No data provided"}), 400
            
        filename = data.get("filename")
        password = data.get("password")
        
        if not filename or not password:
            return jsonify({"status": "error", "message": "Filename and password are required"}), 400
            
        processing_session_id = session.get(SESSION_ID_KEY)
        if not processing_session_id:
            return jsonify({"status": "error", "message": "No active session"}), 400
            
        session_merged_out = os.path.join(FORM16_MERGED_FOLDER, processing_session_id)
        session_signed_out = os.path.join(FORM16_SIGNED_FOLDER, processing_session_id)
        os.makedirs(session_signed_out, exist_ok=True)
        
        input_pdf = os.path.join(session_merged_out, filename)
        output_pdf = os.path.join(session_signed_out, filename)
        
        if not os.path.exists(input_pdf):
            return jsonify({"status": "error", "message": f"Merged PDF not found for {filename}"}), 404
            
        sign_pdf(input_pdf, output_pdf, password)
        return jsonify({"status": "success", "message": "Document signed successfully"})
        
    except ValueError as ve:
        return jsonify({"status": "error", "message": str(ve)}), 401
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@form16_processing_bp.route("/publish", methods=["POST"])
@hr_required
def publish_form16():
    """
    Publish an approved Form16 document for employee portal visibility.
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error", "message": "No JSON data provided"}), 400
        
        filename = data.get("filename")
        pan = data.get("pan")
        employee_name = data.get("employee_name")
        
        if not filename or not pan:
            return jsonify({"status": "error", "message": "filename and pan are required"}), 400
            
        if SESSION_PUBLISHED_KEY not in session:
            session[SESSION_PUBLISHED_KEY] = []
            
        published_records = session[SESSION_PUBLISHED_KEY]
        for record in published_records:
            if record.get("filename") == filename:
                return jsonify({"status": "error", "message": "Document already published"}), 400
                
        publish_record = {
            "pan": pan,
            "employee_name": employee_name,
            "filename": filename,
            "published_at": datetime.now().isoformat(),
            "published_by": session["user"].get("username", "hr_user")
        }
        
        session[SESSION_PUBLISHED_KEY].append(publish_record)
        session.modified = True
        
        _persist_publish_to_csv(filename, pan, session["user"].get("username", "hr_user"))
        _log_publish_to_csv(publish_record)
        
        return jsonify({"status": "success", "message": "Document published successfully"})
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def _persist_publish_to_csv(filename, pan, user_name):
    import tempfile, shutil
    file_exists = os.path.exists(CSV_FORM16_APPROVED)
    if not file_exists:
        return False
        
    temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False, newline='', encoding='utf-8')
    try:
        with open(CSV_FORM16_APPROVED, 'r', newline='', encoding='utf-8') as f, temp_file:
            reader = csv.DictReader(f)
            fieldnames = list(reader.fieldnames) if reader.fieldnames else []
            if "published" not in fieldnames:
                fieldnames.extend(["published", "published_by", "published_at"])
                
            writer = csv.DictWriter(temp_file, fieldnames=fieldnames)
            writer.writeheader()
            
            for row in reader:
                if row.get("filename") == filename and row.get("pan") == pan:
                    row["published"] = "True"
                    row["published_by"] = user_name
                    row["published_at"] = datetime.now().isoformat()
                
                if "published" not in row: row["published"] = "False"
                if "published_by" not in row: row["published_by"] = ""
                if "published_at" not in row: row["published_at"] = ""
                writer.writerow(row)
                
        shutil.move(temp_file.name, CSV_FORM16_APPROVED)
        return True
    except Exception as e:
        print(f"Error publishing to CSV: {e}")
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)
        return False

def _log_publish_to_csv(record):
    try:
        file_exists = os.path.exists(CSV_FORM16_PROCESSING_LOG)
        with open(CSV_FORM16_PROCESSING_LOG, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not file_exists:
                writer.writerow(["timestamp", "action", "pan", "employee_name", "filename", "user", "date"])
            writer.writerow([
                datetime.now().isoformat(), "PUBLISH", record.get("pan"), record.get("employee_name"),
                record.get("filename"), record.get("published_by"), record.get("published_at")
            ])
    except Exception as e:
        print(f"Error logging publish to CSV: {e}")

