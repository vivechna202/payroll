"""
proof_service.py – Investment proof upload & approval.

Phase 3 implementation handles file storage, CSV logging,
and tracking HR remarks with replacing behavior.
"""

import os
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
from config import CSV_PROOFS, UPLOAD_FOLDER
from services.csv_service import read_csv, read_csv_filtered, csv_to_records, append_row, update_row, write_csv


def get_proofs_for_employee(employee_id: str) -> list[dict]:
    """Return all proof submissions for a given employee."""
    return read_csv_filtered(CSV_PROOFS, "employee_id", employee_id).to_dict(orient="records")


def get_all_pending_proofs() -> list[dict]:
    """Return all proofs with status = PENDING. Used by HR approval page."""
    return read_csv_filtered(CSV_PROOFS, "status", "PENDING").to_dict(orient="records")


def get_all_proofs() -> list[dict]:
    """Return every proof record. Used by HR overview."""
    return csv_to_records(CSV_PROOFS)


def allowed_file(filename: str) -> bool:
    """Validate uploaded file extension."""
    ALLOWED = {"pdf", "jpg", "jpeg", "png"}
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED


def submit_proof(employee_id: str, declaration_id: str, section: str, file_obj) -> dict:
    """
    Record a proof submission.
    Saves file to uploads/<employee_id>/<uuid_filename>
    Replaces existing pending/rejected proofs for the same section/declaration.
    """
    emp_folder = os.path.join(UPLOAD_FOLDER, employee_id)
    os.makedirs(emp_folder, exist_ok=True)
    
    file_id = str(uuid.uuid4())[:8].upper()
    original_name = secure_filename(file_obj.filename)
    save_name = f"{file_id}_{original_name}"
    absolute_file_path = os.path.join(emp_folder, save_name)
    
    file_obj.save(absolute_file_path)
    
    now = datetime.now().isoformat()
    relative_path = f"{employee_id}/{save_name}"

    df = read_csv(CSV_PROOFS)
    if not df.empty and "employee_id" in df.columns:
        mask = (df["employee_id"] == employee_id) & \
               (df["declaration_id"] == declaration_id) & \
               (df["section"] == section) & \
               (df["status"].isin(["PENDING", "REJECTED"]))
        
        if mask.any():
            # Update existing
            idx = df.index[mask][0]
            
            # Optional: Delete old physical file (ignoring errors)
            old_rel_path = df.at[idx, "file_path"]
            if old_rel_path:
                old_abs_path = os.path.join(UPLOAD_FOLDER, old_rel_path.replace("/", os.sep))
                if os.path.exists(old_abs_path):
                    try:
                        os.remove(old_abs_path)
                    except Exception:
                        pass
            
            df.at[idx, "file_name"] = original_name
            df.at[idx, "file_path"] = relative_path
            df.at[idx, "status"] = "PENDING"
            df.at[idx, "hr_remarks"] = ""
            df.at[idx, "uploaded_at"] = now
            df.at[idx, "reviewed_at"] = ""
            write_csv(CSV_PROOFS, df)
            return df.iloc[idx].to_dict()

    # Create new
    row = {
        "proof_id": f"PRF-{file_id}",
        "employee_id": employee_id,
        "declaration_id": declaration_id,
        "section": section,
        "file_name": original_name,
        "file_path": relative_path,
        "status": "PENDING",
        "hr_remarks": "",
        "uploaded_at": now,
        "reviewed_at": "",
    }
    append_row(CSV_PROOFS, row)
    return row


def approve_proof(proof_id: str, remarks: str = "") -> bool:
    """Mark a proof as APPROVED."""
    return update_row(CSV_PROOFS, "proof_id", proof_id, {
        "status": "APPROVED",
        "hr_remarks": remarks,
        "reviewed_at": datetime.now().isoformat(),
    })


def reject_proof(proof_id: str, remarks: str = "") -> bool:
    """Mark a proof as REJECTED."""
    return update_row(CSV_PROOFS, "proof_id", proof_id, {
        "status": "REJECTED",
        "hr_remarks": remarks,
        "reviewed_at": datetime.now().isoformat(),
    })
