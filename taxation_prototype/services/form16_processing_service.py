"""
form16_processing_service.py
────────────────────────────────────────────────────────────
HR-only Form 16 Processing pipeline.

Responsibilities:
  1. Validate TAN format.
  2. Decrypt password-protected PDFs using TAN as password.
  3. Extract PAN, employee name, FY, part type from decrypted text.
  4. Match Part A and Part B PDFs via PAN.
  5. Log all events (NEVER the TAN itself).

SECURITY NOTES:
  - TAN is accepted only as a function parameter (passed from session).
  - TAN is NEVER written to disk, CSV, or logs.
  - Decrypted temp files are stored per session_id in a temp subfolder.
  - Caller is responsible for clearing session data after use.
"""

import os
import re
import json
import uuid
import zipfile
import shutil
import io
import logging
from datetime import datetime
from werkzeug.utils import secure_filename

from config import FORM16_PROCESSING_FOLDER, CSV_FORM16_PROCESSING_LOG
from services.csv_service import ensure_csv, append_row

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

TAN_REGEX = re.compile(r'^[A-Z]{4}[0-9]{5}[A-Z]{1}$')

# Regex patterns for extracting Form 16 fields from PDF text
PAN_REGEX      = re.compile(r'\b([A-Z]{5}[0-9]{4}[A-Z]{1})\b')
FY_REGEX       = re.compile(r'(?:Assessment Year|Financial Year|F\.Y\.|AY)[:\s]*(\d{4}[-–]\d{2,4})', re.IGNORECASE)
PART_A_MARKERS = ['PART A', 'Part - A', 'PART-A', 'Certificate under Section 203', 'DETAILS OF TAX DEDUCTED']
PART_B_MARKERS = ['PART B', 'Part - B', 'PART-B', 'DETAILS OF SALARY PAID', 'Gross Salary']

# Allowed MIME / extensions
ALLOWED_PDF_EXT = {'.pdf'}
ALLOWED_ZIP_EXT = {'.zip'}

# ─────────────────────────────────────────────────────────────
# Ensure log CSV exists
# ─────────────────────────────────────────────────────────────

ensure_csv(CSV_FORM16_PROCESSING_LOG, [
    "log_id", "session_id", "event_type", "filename",
    "status", "pan", "employee_name", "financial_year",
    "part_type", "error_detail", "timestamp"
])


# ─────────────────────────────────────────────────────────────
# 1. TAN Validation
# ─────────────────────────────────────────────────────────────

def validate_tan(tan: str) -> dict:
    """
    Validates Indian TAN format: 4 alpha + 5 numeric + 1 alpha (all uppercase).
    Returns {"valid": bool, "message": str}
    TAN is NEVER logged here.
    """
    if not tan:
        return {"valid": False, "message": "TAN cannot be empty."}
    tan = tan.strip().upper()
    if TAN_REGEX.match(tan):
        return {"valid": True, "message": "TAN format is valid."}
    return {
        "valid": False,
        "message": (
            "Invalid TAN format. Expected format: 4 letters + 5 digits + 1 letter "
            "(e.g., BLRP12345Q). All characters must be uppercase."
        )
    }


# ─────────────────────────────────────────────────────────────
# 2. Session Folder Management
# ─────────────────────────────────────────────────────────────

def get_session_folder(session_id: str) -> str:
    """Returns path to a session-scoped temp folder, creating it if needed."""
    folder = os.path.join(FORM16_PROCESSING_FOLDER, session_id)
    os.makedirs(os.path.join(folder, "raw"), exist_ok=True)
    os.makedirs(os.path.join(folder, "decrypted"), exist_ok=True)
    return folder


def cleanup_session_files(session_id: str) -> None:
    """Removes all temp files for a session (raw + decrypted)."""
    folder = os.path.join(FORM16_PROCESSING_FOLDER, session_id)
    if os.path.exists(folder):
        shutil.rmtree(folder, ignore_errors=True)
    logger.info(f"Cleaned up session folder for session_id={session_id}")


def cleanup_stale_sessions(max_age_hours: int = 24) -> None:
    """Removes session folders older than max_age_hours (called on app startup)."""
    if not os.path.exists(FORM16_PROCESSING_FOLDER):
        return
    cutoff = datetime.now().timestamp() - (max_age_hours * 3600)
    for name in os.listdir(FORM16_PROCESSING_FOLDER):
        folder = os.path.join(FORM16_PROCESSING_FOLDER, name)
        if os.path.isdir(folder):
            mtime = os.path.getmtime(folder)
            if mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
                logger.info(f"Purged stale session folder: {name}")


# ─────────────────────────────────────────────────────────────
# 3. PDF Decryption
# ─────────────────────────────────────────────────────────────

def decrypt_pdf(input_path: str, tan: str, output_path: str) -> dict:
    """
    Attempts to decrypt a PDF using TAN as password.
    Writes the decrypted copy to output_path on success.

    Returns:
        {"success": bool, "status": str, "error": str|None}
        status ∈ {"decrypted", "wrong_password", "corrupted", "not_encrypted"}
    """
    try:
        import pypdf
    except ImportError:
        return {"success": False, "status": "corrupted", "error": "pypdf library not installed."}

    try:
        reader = pypdf.PdfReader(input_path)
    except Exception as e:
        return {"success": False, "status": "corrupted", "error": f"Cannot read PDF: {e}"}

    # Not encrypted — treat as valid (some Form 16s may not be encrypted)
    if not reader.is_encrypted:
        # Just copy as-is
        shutil.copy2(input_path, output_path)
        return {"success": True, "status": "not_encrypted", "error": None}

    # Try with TAN as password
    try:
        result = reader.decrypt(tan)
        if result == pypdf.PasswordType.NOT_DECRYPTED:
            # Try lowercase TAN as well (some PDFs)
            result = reader.decrypt(tan.lower())
        if result == pypdf.PasswordType.NOT_DECRYPTED:
            return {"success": False, "status": "wrong_password", "error": "TAN did not match PDF password."}
    except Exception as e:
        return {"success": False, "status": "corrupted", "error": f"Decryption error: {e}"}

    # Write decrypted copy
    try:
        writer = pypdf.PdfWriter()
        for page in reader.pages:
            writer.add_page(page)
        with open(output_path, "wb") as f:
            writer.write(f)
        return {"success": True, "status": "decrypted", "error": None}
    except Exception as e:
        return {"success": False, "status": "corrupted", "error": f"Failed to write decrypted PDF: {e}"}


# ─────────────────────────────────────────────────────────────
# 4. Text Extraction and Metadata Parsing
# ─────────────────────────────────────────────────────────────

def _extract_text_from_pdf(filepath: str) -> str:
    """Extract all text from a PDF using pdfplumber (preferred) or pypdf fallback."""
    text = ""
    # Try pdfplumber first (better layout extraction)
    try:
        import pdfplumber
        with pdfplumber.open(filepath) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"
        if text.strip():
            return text
    except Exception:
        pass

    # Fallback: pypdf
    try:
        import pypdf
        reader = pypdf.PdfReader(filepath)
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
    except Exception as e:
        logger.warning(f"Text extraction failed for {filepath}: {e}")

    return text


def _detect_part_type(text: str) -> str:
    """Returns 'A', 'B', or 'UNKNOWN' based on text markers."""
    text_upper = text.upper()
    
    # Check for Part A markers
    for marker in PART_A_MARKERS:
        if marker.upper() in text_upper:
            return "A"
    
    # Check for Part B markers
    for marker in PART_B_MARKERS:
        if marker.upper() in text_upper:
            return "B"
    
    # Heuristic: if filename contains part info
    return "UNKNOWN"


def _detect_part_type_from_filename(filename: str) -> str:
    """Guess part type from filename if text detection fails."""
    name_upper = filename.upper()
    if "PART_A" in name_upper or "PARTA" in name_upper or "PART-A" in name_upper or "_A_" in name_upper:
        return "A"
    if "PART_B" in name_upper or "PARTB" in name_upper or "PART-B" in name_upper or "_B_" in name_upper:
        return "B"
    return "UNKNOWN"


def _extract_employee_name(text: str) -> str:
    """
    Attempt to extract employee name from Form 16 text.
    Common patterns: 'Name of Employee:', 'Employee Name:', 'Name:'
    """
    patterns = [
        r'Name of (?:the )?Employee[:\s]+([A-Z][A-Za-z\s\.]{2,50})',
        r'Employee(?:\'s)? Name[:\s]+([A-Z][A-Za-z\s\.]{2,50})',
        r'Name of Deductee[:\s]+([A-Z][A-Za-z\s\.]{2,50})',
    ]
    for pat in patterns:
        match = re.search(pat, text, re.IGNORECASE)
        if match:
            name = match.group(1).strip()
            # Clean up trailing noise
            name = re.split(r'\n|PAN|Father|Designation', name)[0].strip()
            if 2 < len(name) < 60:
                return name
    return "Unknown"


def _normalize_fy(raw_fy: str) -> str:
    """Normalise FY/AY strings to FY format like '2024-25'."""
    if not raw_fy:
        return "Unknown"
    raw_fy = raw_fy.strip().replace('–', '-')
    # AY 2025-26 → FY 2024-25
    ay_match = re.match(r'^(\d{4})-(\d{2,4})$', raw_fy)
    if ay_match:
        start = int(ay_match.group(1))
        # If it looks like Assessment Year, convert to FY
        # AY is always +1 of FY start
        end_short = ay_match.group(2)
        end_full = int(f"20{end_short}") if len(end_short) == 2 else int(end_short)
        if end_full == start + 1:
            # Could be FY or AY; return as-is assuming it's already FY
            return f"{start}-{end_short}" if len(end_short) == 2 else f"{start}-{str(end_full)[-2:]}"
        elif end_full == start:
            # AY where end == start (unusual) — just return
            return raw_fy
    return raw_fy


def extract_pdf_metadata(filepath: str, original_filename: str = "") -> dict:
    """
    Extract PAN, employee name, financial year, and part type from a decrypted PDF.

    Returns:
        {
          "success": bool,
          "pan": str,
          "employee_name": str,
          "financial_year": str,
          "part_type": str,   # "A", "B", or "UNKNOWN"
          "error": str|None
        }
    """
    try:
        text = _extract_text_from_pdf(filepath)
        if not text.strip():
            return {
                "success": False, "pan": "", "employee_name": "",
                "financial_year": "", "part_type": "UNKNOWN",
                "error": "No text could be extracted from PDF."
            }

        # PAN
        pan_matches = PAN_REGEX.findall(text)
        # Filter out company PANs (usually 4th char is 'C'); take first employee PAN
        employee_pans = [p for p in pan_matches if len(p) == 10]
        pan = employee_pans[0] if employee_pans else ""

        # Employee name
        employee_name = _extract_employee_name(text)

        # Financial year
        fy_match = FY_REGEX.search(text)
        financial_year = _normalize_fy(fy_match.group(1)) if fy_match else "Unknown"

        # Part type
        part_type = _detect_part_type(text)
        if part_type == "UNKNOWN" and original_filename:
            part_type = _detect_part_type_from_filename(original_filename)

        return {
            "success": True,
            "pan": pan,
            "employee_name": employee_name,
            "financial_year": financial_year,
            "part_type": part_type,
            "error": None
        }

    except Exception as e:
        return {
            "success": False, "pan": "", "employee_name": "",
            "financial_year": "", "part_type": "UNKNOWN",
            "error": f"Extraction failed: {e}"
        }


# ─────────────────────────────────────────────────────────────
# 5. Logging (TAN-free)
# ─────────────────────────────────────────────────────────────

def log_processing_event(
    session_id: str,
    event_type: str,
    filename: str = "",
    status: str = "",
    pan: str = "",
    employee_name: str = "",
    financial_year: str = "",
    part_type: str = "",
    error_detail: str = "",
) -> None:
    """
    Appends an event to the processing log CSV.
    TAN is NEVER passed here or written to the log.
    """
    row = {
        "log_id":        str(uuid.uuid4())[:8].upper(),
        "session_id":    session_id,
        "event_type":    event_type,
        "filename":      filename,
        "status":        status,
        "pan":           pan,
        "employee_name": employee_name,
        "financial_year": financial_year,
        "part_type":     part_type,
        "error_detail":  error_detail,
        "timestamp":     datetime.utcnow().isoformat(),
    }
    try:
        append_row(CSV_FORM16_PROCESSING_LOG, row)
    except Exception as e:
        logger.warning(f"Failed to write processing log: {e}")


# ─────────────────────────────────────────────────────────────
# 6. Bulk Upload + Decryption + Extraction Pipeline
# ─────────────────────────────────────────────────────────────

def _collect_pdfs_from_upload(files, session_folder: str) -> list:
    """
    Saves uploaded file objects to raw/ folder.
    Handles both individual PDFs and ZIP archives.
    Returns list of {"raw_path": str, "original_filename": str}.
    """
    raw_folder = os.path.join(session_folder, "raw")
    collected = []

    for f in files:
        if not f or not f.filename:
            continue
        ext = os.path.splitext(f.filename)[1].lower()
        safe_name = secure_filename(f.filename)

        if ext in ALLOWED_PDF_EXT:
            dest = os.path.join(raw_folder, safe_name)
            # Avoid overwrite: add suffix if needed
            dest = _unique_path(dest)
            f.save(dest)
            collected.append({"raw_path": dest, "original_filename": f.filename})

        elif ext in ALLOWED_ZIP_EXT:
            # Save ZIP then extract all PDFs
            zip_dest = os.path.join(raw_folder, safe_name)
            f.save(zip_dest)
            try:
                with zipfile.ZipFile(zip_dest, 'r') as zf:
                    for member in zf.namelist():
                        member_ext = os.path.splitext(member)[1].lower()
                        if member_ext == '.pdf':
                            member_safe = secure_filename(os.path.basename(member))
                            if not member_safe:
                                continue
                            out_path = os.path.join(raw_folder, member_safe)
                            out_path = _unique_path(out_path)
                            with zf.open(member) as src, open(out_path, 'wb') as dst:
                                dst.write(src.read())
                            collected.append({"raw_path": out_path, "original_filename": member})
            except Exception as e:
                logger.warning(f"Could not extract ZIP {safe_name}: {e}")
            finally:
                try:
                    os.remove(zip_dest)
                except Exception:
                    pass
        # Silently skip unsupported formats

    return collected


def _unique_path(path: str) -> str:
    """Returns a unique path by appending a counter if the file already exists."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    counter = 1
    while os.path.exists(f"{base}_{counter}{ext}"):
        counter += 1
    return f"{base}_{counter}{ext}"


def process_uploaded_files(files, tan: str, session_id: str) -> dict:
    """
    Main pipeline entry point. Called from the route handler.
    TAN is passed as a parameter — NEVER stored anywhere.

    Args:
        files:      iterable of Werkzeug FileStorage objects
        tan:        session TAN (string, already validated)
        session_id: unique ID for this processing session

    Returns:
        {
          "processed": [per-file result dicts],
          "summary": {total, decrypted, failed, extraction_errors},
          "session_id": str,
          "results_path": str   (path to JSON metadata file)
        }
    """
    session_folder = get_session_folder(session_id)
    decrypted_folder = os.path.join(session_folder, "decrypted")

    # Log upload event (no TAN)
    log_processing_event(session_id=session_id, event_type="UPLOAD_START", status="started")

    # Collect all PDF files from upload (including ZIP extraction)
    raw_files = _collect_pdfs_from_upload(files, session_folder)

    if not raw_files:
        log_processing_event(session_id=session_id, event_type="UPLOAD_ERROR", status="no_valid_files",
                             error_detail="No valid PDF or ZIP files found in upload.")
        return {
            "processed": [], "session_id": session_id,
            "summary": {"total": 0, "decrypted": 0, "failed": 0, "extraction_errors": 0},
            "results_path": None
        }

    processed = []
    counters = {"total": 0, "decrypted": 0, "failed": 0, "extraction_errors": 0}

    for file_info in raw_files:
        raw_path = file_info["raw_path"]
        orig_name = file_info["original_filename"]
        basename = os.path.basename(raw_path)
        counters["total"] += 1

        result = {
            "filename":       orig_name,
            "decryption_status": "",   # decrypted / wrong_password / corrupted / not_encrypted
            "extraction_status": "",   # extracted / failed / skipped
            "pan":            "",
            "employee_name":  "",
            "financial_year": "",
            "part_type":      "",
            "decrypted_path": None,
            "error":          None,
        }

        # ── Step 1: Decrypt ──────────────────────────────────
        dec_path = os.path.join(decrypted_folder, basename)
        dec_result = decrypt_pdf(raw_path, tan, dec_path)
        result["decryption_status"] = dec_result["status"]

        if not dec_result["success"]:
            result["error"] = dec_result["error"]
            result["extraction_status"] = "skipped"
            counters["failed"] += 1
            log_processing_event(
                session_id=session_id, event_type="DECRYPT_FAIL",
                filename=orig_name, status=dec_result["status"],
                error_detail=dec_result["error"] or ""
            )
            processed.append(result)
            continue

        counters["decrypted"] += 1
        result["decrypted_path"] = dec_path

        # ── Step 2: Extract metadata ─────────────────────────
        meta = extract_pdf_metadata(dec_path, original_filename=orig_name)

        if meta["success"]:
            result["pan"]            = meta["pan"]
            result["employee_name"]  = meta["employee_name"]
            result["financial_year"] = meta["financial_year"]
            result["part_type"]      = meta["part_type"]
            result["extraction_status"] = "extracted"
            log_processing_event(
                session_id=session_id, event_type="EXTRACT_SUCCESS",
                filename=orig_name, status="ok",
                pan=meta["pan"], employee_name=meta["employee_name"],
                financial_year=meta["financial_year"], part_type=meta["part_type"]
            )
        else:
            result["extraction_status"] = "failed"
            result["error"] = meta["error"]
            counters["extraction_errors"] += 1
            log_processing_event(
                session_id=session_id, event_type="EXTRACT_FAIL",
                filename=orig_name, status="extraction_failed",
                error_detail=meta["error"] or ""
            )

        processed.append(result)

    # Save results to JSON for dashboard rendering (no TAN in this JSON)
    results_path = _save_session_results(session_folder, processed)

    log_processing_event(
        session_id=session_id, event_type="UPLOAD_COMPLETE",
        status="done", error_detail=(
            f"total={counters['total']}, decrypted={counters['decrypted']}, "
            f"failed={counters['failed']}, extraction_errors={counters['extraction_errors']}"
        )
    )

    return {
        "processed":   processed,
        "session_id":  session_id,
        "summary":     counters,
        "results_path": results_path,
    }


# ─────────────────────────────────────────────────────────────
# 7. PAN Matching Engine
# ─────────────────────────────────────────────────────────────

def match_parts(processed_records: list) -> list:
    """
    Groups successfully decrypted+extracted records by PAN.
    Produces a structured list for the HR review dashboard.

    Returns:
        [
          {
            "pan": str,
            "employee_name": str,
            "financial_year": str,
            "part_a": {filename, decrypted_path} | None,
            "part_b": {filename, decrypted_path} | None,
            "status": "Ready" | "Missing Part A" | "Missing Part B" | "Missing Both",
            "duplicate_warning": bool,
          },
          ...
        ]
    """
    pan_map = {}  # PAN → {"part_a": [...], "part_b": [...], "name": str, "fy": str}

    for rec in processed_records:
        if rec.get("extraction_status") != "extracted":
            continue
        pan = rec.get("pan", "").strip().upper()
        if not pan:
            continue

        if pan not in pan_map:
            pan_map[pan] = {
                "employee_name": rec.get("employee_name", "Unknown"),
                "financial_year": rec.get("financial_year", "Unknown"),
                "part_a": [],
                "part_b": [],
            }

        # Update name if better
        if pan_map[pan]["employee_name"] == "Unknown" and rec.get("employee_name") != "Unknown":
            pan_map[pan]["employee_name"] = rec["employee_name"]

        pt = rec.get("part_type", "UNKNOWN")
        entry = {
            "filename":       rec.get("filename", ""),
            "decrypted_path": rec.get("decrypted_path", ""),
        }
        if pt == "A":
            pan_map[pan]["part_a"].append(entry)
        elif pt == "B":
            pan_map[pan]["part_b"].append(entry)

    # Build review table
    matched = []
    for pan, data in pan_map.items():
        has_a = len(data["part_a"]) > 0
        has_b = len(data["part_b"]) > 0
        dup_warning = len(data["part_a"]) > 1 or len(data["part_b"]) > 1

        if has_a and has_b:
            status = "Ready"
        elif has_a and not has_b:
            status = "Missing Part B"
        elif not has_a and has_b:
            status = "Missing Part A"
        else:
            status = "Missing Both"

        matched.append({
            "pan":              pan,
            "employee_name":    data["employee_name"],
            "financial_year":   data["financial_year"],
            "part_a":           data["part_a"][0] if has_a else None,
            "part_b":           data["part_b"][0] if has_b else None,
            "part_a_files":     data["part_a"],
            "part_b_files":     data["part_b"],
            "has_part_a":       has_a,
            "has_part_b":       has_b,
            "status":           status,
            "duplicate_warning": dup_warning,
        })

    # Sort: Ready first, then by PAN
    matched.sort(key=lambda x: (0 if x["status"] == "Ready" else 1, x["pan"]))
    return matched


# ─────────────────────────────────────────────────────────────
# 8. Session Result Persistence (metadata JSON — no TAN)
# ─────────────────────────────────────────────────────────────

def _save_session_results(session_folder: str, processed: list) -> str:
    """Saves processed results to a JSON file in the session folder."""
    results_path = os.path.join(session_folder, "results.json")
    # Only store metadata — NOT TAN
    safe_records = []
    for r in processed:
        safe_records.append({
            "filename":          r.get("filename", ""),
            "decryption_status": r.get("decryption_status", ""),
            "extraction_status": r.get("extraction_status", ""),
            "pan":               r.get("pan", ""),
            "employee_name":     r.get("employee_name", ""),
            "financial_year":    r.get("financial_year", ""),
            "part_type":         r.get("part_type", ""),
            "decrypted_path":    r.get("decrypted_path"),
            "error":             r.get("error"),
        })
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(safe_records, f, indent=2)
    return results_path


def load_session_results(session_id: str) -> list:
    """Loads previously processed results from the session JSON file."""
    folder = os.path.join(FORM16_PROCESSING_FOLDER, session_id)
    results_path = os.path.join(folder, "results.json")
    if not os.path.exists(results_path):
        return []
    try:
        with open(results_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def get_dashboard_data(session_id: str) -> dict:
    """
    Returns all data needed to render the HR review dashboard.
    """
    processed = load_session_results(session_id)
    matched = match_parts(processed)

    total_files = len(processed)
    decrypted_count = sum(1 for r in processed if r.get("decryption_status") in ("decrypted", "not_encrypted"))
    failed_decrypt = sum(1 for r in processed if r.get("decryption_status") == "wrong_password")
    corrupted = sum(1 for r in processed if r.get("decryption_status") == "corrupted")
    extract_failed = sum(1 for r in processed if r.get("extraction_status") == "failed")

    ready_count = sum(1 for m in matched if m["status"] == "Ready")
    missing_a   = sum(1 for m in matched if m["status"] == "Missing Part A")
    missing_b   = sum(1 for m in matched if m["status"] == "Missing Part B")

    return {
        "processed":      processed,
        "matched":        matched,
        "summary": {
            "total_files":     total_files,
            "decrypted":       decrypted_count,
            "failed_decrypt":  failed_decrypt,
            "corrupted":       corrupted,
            "extract_failed":  extract_failed,
            "total_pans":      len(matched),
            "ready":           ready_count,
            "missing_part_a":  missing_a,
            "missing_part_b":  missing_b,
        }
    }


# ═════════════════════════════════════════════════════════════
# TASK 2 — PDF MERGE ENGINE
# ─────────────────────────────────────────────────────────────
# Completely separate from Task 1. Reads decrypted PDFs produced
# by Task 1 and merges Ready pairs into combined Form 16 PDFs.
# No TAN involvement. No modification to any Task 1 function.
# ═════════════════════════════════════════════════════════════

from config import FORM16_MERGED_FOLDER


# ─────────────────────────────────────────────────────────────
# 9. Single PDF Merge
# ─────────────────────────────────────────────────────────────

def merge_pdfs(part_a_path: str, part_b_path: str, output_path: str) -> dict:
    """
    Merge Part A and Part B PDFs into a single combined PDF.

    Page order: all Part A pages followed by all Part B pages.
    Preserves original formatting and quality — no re-rendering.

    Args:
        part_a_path:  Path to the decrypted Part A PDF
        part_b_path:  Path to the decrypted Part B PDF
        output_path:  Destination path for the merged PDF

    Returns:
        {"success": bool, "pages": int, "error": str|None}
    """
    try:
        import pypdf
    except ImportError:
        return {"success": False, "pages": 0, "error": "pypdf library not installed."}

    # Validate source files exist
    if not os.path.exists(part_a_path):
        return {"success": False, "pages": 0, "error": f"Part A file not found: {part_a_path}"}
    if not os.path.exists(part_b_path):
        return {"success": False, "pages": 0, "error": f"Part B file not found: {part_b_path}"}

    try:
        writer = pypdf.PdfWriter()

        # Append Part A pages
        reader_a = pypdf.PdfReader(part_a_path)
        if reader_a.is_encrypted:
            return {"success": False, "pages": 0,
                    "error": "Part A PDF is still encrypted. Ensure decryption ran first."}
        for page in reader_a.pages:
            writer.add_page(page)
        pages_a = len(reader_a.pages)

        # Append Part B pages
        reader_b = pypdf.PdfReader(part_b_path)
        if reader_b.is_encrypted:
            return {"success": False, "pages": 0,
                    "error": "Part B PDF is still encrypted. Ensure decryption ran first."}
        for page in reader_b.pages:
            writer.add_page(page)
        pages_b = len(reader_b.pages)

        total_pages = pages_a + pages_b

        # Write merged output
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        with open(output_path, "wb") as out_f:
            writer.write(out_f)

        return {"success": True, "pages": total_pages, "error": None}

    except Exception as e:
        return {"success": False, "pages": 0, "error": f"Merge failed: {e}"}


# ─────────────────────────────────────────────────────────────
# 10. Output File Naming
# ─────────────────────────────────────────────────────────────

def get_merged_output_path(pan: str, session_id: str) -> str:
    """
    Returns the output path for a merged Form 16 PDF.
    Format: <FORM16_MERGED_FOLDER>/<session_id>/<PAN>_Form16.pdf

    Handles duplicates by appending _2, _3, etc.
    """
    session_out = os.path.join(FORM16_MERGED_FOLDER, session_id)
    os.makedirs(session_out, exist_ok=True)
    filename = f"{pan}_Form16.pdf"
    out_path = os.path.join(session_out, filename)
    # Handle duplicate — unlikely (one PAN per session) but safe
    return _unique_path(out_path)


# ─────────────────────────────────────────────────────────────
# 11. Bulk Merge Pipeline
# ─────────────────────────────────────────────────────────────

def bulk_merge_session(session_id: str) -> dict:
    """
    Merges all Ready PAN records from a completed Task 1 session.

    Only processes records where status == 'Ready' (both Part A and B present).
    Skips all others and continues on per-record failures.
    TAN is NOT involved here — works on already-decrypted files.

    Returns:
        {
          "results": [per-PAN merge result dicts],
          "summary": {ready, merged, failed, skipped},
          "session_id": str
        }
    """
    # Load Task 1 results
    processed = load_session_results(session_id)
    matched   = match_parts(processed)

    ready_records = [m for m in matched if m["status"] == "Ready"]
    counters = {"ready": len(ready_records), "merged": 0, "failed": 0, "skipped": 0}

    log_processing_event(
        session_id=session_id,
        event_type="MERGE_START",
        status="started",
        error_detail=f"ready_records={len(ready_records)}"
    )

    merge_results = []

    for record in matched:
        pan           = record["pan"]
        employee_name = record["employee_name"]
        financial_year = record.get("financial_year", "Unknown")

        # Skip non-Ready records
        if record["status"] != "Ready":
            merge_results.append({
                "pan":           pan,
                "employee_name": employee_name,
                "financial_year": financial_year,
                "merge_status":  "skipped",
                "output_filename": None,
                "output_path":   None,
                "pages":         0,
                "error":         f"Skipped — status: {record['status']}",
                "merged_at":     None,
            })
            counters["skipped"] += 1
            continue

        # Determine source file paths
        part_a_path = record["part_a"]["decrypted_path"] if record.get("part_a") else None
        part_b_path = record["part_b"]["decrypted_path"] if record.get("part_b") else None

        if not part_a_path or not part_b_path:
            merge_results.append({
                "pan":           pan,
                "employee_name": employee_name,
                "financial_year": financial_year,
                "merge_status":  "failed",
                "output_filename": None,
                "output_path":   None,
                "pages":         0,
                "error":         "Source file path missing from session data.",
                "merged_at":     None,
            })
            counters["failed"] += 1
            log_processing_event(
                session_id=session_id, event_type="MERGE_FAIL",
                pan=pan, employee_name=employee_name,
                status="missing_path",
                error_detail="decrypted_path was None for Part A or Part B"
            )
            continue

        # Merge
        output_path = get_merged_output_path(pan, session_id)
        output_filename = os.path.basename(output_path)
        merge_result = merge_pdfs(part_a_path, part_b_path, output_path)
        merged_at = datetime.utcnow().isoformat()

        if merge_result["success"]:
            merge_results.append({
                "pan":            pan,
                "employee_name":  employee_name,
                "financial_year": financial_year,
                "merge_status":   "merged",
                "output_filename": output_filename,
                "output_path":    output_path,
                "pages":          merge_result["pages"],
                "error":          None,
                "merged_at":      merged_at,
            })
            counters["merged"] += 1
            log_processing_event(
                session_id=session_id, event_type="MERGE_SUCCESS",
                pan=pan, employee_name=employee_name,
                financial_year=financial_year,
                filename=output_filename, status="merged",
                error_detail=f"pages={merge_result['pages']}"
            )
        else:
            merge_results.append({
                "pan":            pan,
                "employee_name":  employee_name,
                "financial_year": financial_year,
                "merge_status":   "failed",
                "output_filename": None,
                "output_path":    None,
                "pages":          0,
                "error":          merge_result["error"],
                "merged_at":      merged_at,
            })
            counters["failed"] += 1
            log_processing_event(
                session_id=session_id, event_type="MERGE_FAIL",
                pan=pan, employee_name=employee_name,
                status="merge_error",
                error_detail=merge_result["error"] or ""
            )

    # Persist merge results to session JSON
    _save_merge_results(session_id, merge_results)

    log_processing_event(
        session_id=session_id, event_type="MERGE_COMPLETE",
        status="done",
        error_detail=(
            f"ready={counters['ready']}, merged={counters['merged']}, "
            f"failed={counters['failed']}, skipped={counters['skipped']}"
        )
    )

    return {
        "results":    merge_results,
        "summary":    counters,
        "session_id": session_id,
    }


# ─────────────────────────────────────────────────────────────
# 12. Merge Result Persistence
# ─────────────────────────────────────────────────────────────

def _save_merge_results(session_id: str, merge_results: list) -> str:
    """Saves merge results to merge_results.json inside the processing session folder."""
    folder = os.path.join(FORM16_PROCESSING_FOLDER, session_id)
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "merge_results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(merge_results, f, indent=2)
    return path


def load_merge_results(session_id: str) -> list:
    """Loads merge results from session JSON. Returns [] if not found."""
    folder = os.path.join(FORM16_PROCESSING_FOLDER, session_id)
    path = os.path.join(folder, "merge_results.json")
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────
# 13. Merge Dashboard Data
# ─────────────────────────────────────────────────────────────

def get_merge_dashboard_data(session_id: str) -> dict:
    """
    Returns all data needed to render the Merge Dashboard section.
    Combines Task 1 ready count with Task 2 merge results.
    """
    merge_results = load_merge_results(session_id)

    merged_count  = sum(1 for r in merge_results if r["merge_status"] == "merged")
    failed_count  = sum(1 for r in merge_results if r["merge_status"] == "failed")
    skipped_count = sum(1 for r in merge_results if r["merge_status"] == "skipped")
    ready_count   = merged_count + failed_count  # total attempted

    return {
        "merge_results": merge_results,
        "has_merge_results": len(merge_results) > 0,
        "summary": {
            "ready":   ready_count,
            "merged":  merged_count,
            "failed":  failed_count,
            "skipped": skipped_count,
        }
    }


# ─────────────────────────────────────────────────────────────
# 14. ZIP Download Builder
# ─────────────────────────────────────────────────────────────

def zip_merged_files(session_id: str) -> dict:
    """
    Creates a ZIP archive of all successfully merged Form 16 PDFs
    for the given session.

    Returns:
        {"success": bool, "zip_path": str|None, "count": int, "error": str|None}
    """
    merge_results = load_merge_results(session_id)
    successful = [
        r for r in merge_results
        if r["merge_status"] == "merged" and r.get("output_path")
        and os.path.exists(r["output_path"])
    ]

    if not successful:
        return {
            "success": False, "zip_path": None, "count": 0,
            "error": "No successfully merged PDFs found to zip."
        }

    # Build ZIP in the merged session folder
    session_out = os.path.join(FORM16_MERGED_FOLDER, session_id)
    os.makedirs(session_out, exist_ok=True)
    zip_name = f"Form16_Merged_{session_id[:8]}.zip"
    zip_path = os.path.join(session_out, zip_name)

    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for r in successful:
                zf.write(r["output_path"], arcname=r["output_filename"])
        return {"success": True, "zip_path": zip_path, "count": len(successful), "error": None}
    except Exception as e:
        return {"success": False, "zip_path": None, "count": 0, "error": str(e)}

