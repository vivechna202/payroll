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

from flask import (
    Blueprint, render_template, session, redirect, url_for,
    flash, request, jsonify, send_file, abort
)
from functools import wraps

from config import (
    CURRENT_FY, CSV_FORM16_PROCESSING_LOG, FORM16_PROCESSING_FOLDER
)
from services.form16_processing_service import (
    validate_tan,
    process_uploaded_files,
    get_dashboard_data,
    cleanup_session_files,
    load_session_results,
    match_parts,
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
    Shows TAN input, upload form (if TAN set), and results (if processed).
    """
    user = session["user"]
    tan_set = SESSION_TAN_KEY in session and bool(session[SESSION_TAN_KEY])
    processing_session_id = session.get(SESSION_ID_KEY)
    has_results = session.get(SESSION_PROCESSED_KEY, False)

    dashboard_data = None
    if has_results and processing_session_id:
        try:
            dashboard_data = get_dashboard_data(processing_session_id)
        except Exception:
            has_results = False

    return render_template(
        "hr/form16_processing.html",
        user=user,
        tan_set=tan_set,
        has_results=has_results,
        dashboard_data=dashboard_data,
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
    if old_id:
        cleanup_session_files(old_id)


def _full_session_clear():
    """Remove TAN + all processing session data from session and disk."""
    session.pop(SESSION_TAN_KEY, None)
    old_id = session.pop(SESSION_ID_KEY, None)
    session.pop(SESSION_PROCESSED_KEY, None)
    if old_id:
        cleanup_session_files(old_id)
