"""
challan_service.py – CRUD operations for Challan Management with CSV persistence.

Provides add, update, delete, query functions for ITNS 281 challan records
stored in challans.csv. Includes server-side validation for duplicate
prevention and field-level checks.
"""

import re
import uuid
import pandas as pd
from app.base.utils.config import CSV_CHALLANS
from app.base.utils.csv_service import read_csv, append_row, write_csv


# ─────────────────────────────────────────────────────────────
# Query helpers
# ─────────────────────────────────────────────────────────────

def get_all_challans():
    """Return all challans as a list of dicts."""
    df = read_csv(CSV_CHALLANS)
    if df.empty:
        return []
    return df.to_dict(orient="records")


def get_challans_by_quarter(quarter, fy):
    """Return challans for a specific quarter and financial year."""
    df = read_csv(CSV_CHALLANS)

    if df.empty:
        return []

    df = df[
        (df["quarter"] == quarter) &
        (df["financial_year"] == fy)
    ]

    return df.to_dict(orient="records")


def get_quarter_challans(quarter, fy):
    """Return challans for a quarter (alias for get_challans_by_quarter)."""
    return get_challans_by_quarter(quarter, fy)


def get_challan(challan_id):
    """Get a single challan by its ID."""
    df = read_csv(CSV_CHALLANS)

    if df.empty:
        return None

    row = df[df["challan_id"] == challan_id]

    if row.empty:
        return None

    return row.iloc[0].to_dict()


# ─────────────────────────────────────────────────────────────
# Validation
# ─────────────────────────────────────────────────────────────

def validate_challan_fields(data):
    """
    Validate challan fields and return list of error messages.
    Returns empty list if all validations pass.
    """
    errors = []

    # Required fields
    required = ["quarter", "financial_year", "bsr_code", "challan_serial_no", "challan_date", "challan_amount"]
    for field in required:
        if not data.get(field) and data.get(field) != 0:
            errors.append(f"Missing required field: {field}")

    if errors:
        return errors

    # BSR Code: exactly 7 digits
    bsr = str(data["bsr_code"]).strip()
    if not re.match(r"^\d{7}$", bsr):
        errors.append("BSR Code must be exactly 7 digits.")

    # Challan Number: exactly 5 digits
    challan_no = str(data["challan_serial_no"]).strip()
    if not re.match(r"^\d{5}$", challan_no):
        errors.append("Challan Number must be exactly 5 digits.")

    # Amount > 0
    try:
        amount = float(data["challan_amount"])
        if amount <= 0:
            errors.append("Challan Amount must be greater than zero.")
    except (ValueError, TypeError):
        errors.append("Challan Amount must be a valid number.")

    # Quarter validation
    if data["quarter"] not in ("Q1", "Q2", "Q3", "Q4"):
        errors.append("Quarter must be one of: Q1, Q2, Q3, Q4.")

    # Challan date must be non-empty
    if not str(data["challan_date"]).strip():
        errors.append("Challan Date is required.")

    return errors


def check_duplicate(bsr_code, challan_serial_no, challan_date, exclude_id=None):
    """
    Check if a challan with the same BSR Code + Challan Number + Date already exists.
    Returns True if duplicate found, False otherwise.
    Optionally exclude a challan_id (for edit operations).
    """
    df = read_csv(CSV_CHALLANS)
    if df.empty:
        return False

    mask = (
        (df["bsr_code"] == str(bsr_code).strip()) &
        (df["challan_serial_no"] == str(challan_serial_no).strip()) &
        (df["challan_date"] == str(challan_date).strip())
    )

    if exclude_id:
        mask = mask & (df["challan_id"] != str(exclude_id))

    return mask.any()


# ─────────────────────────────────────────────────────────────
# CRUD operations
# ─────────────────────────────────────────────────────────────

def save_challan(data):
    """
    Validate and add a new challan. Returns dict with status/message.
    Auto-generates a unique challan_id.
    """
    # Field validation
    errors = validate_challan_fields(data)
    if errors:
        return {"status": "error", "message": "; ".join(errors)}

    # Duplicate check
    if check_duplicate(data["bsr_code"], data["challan_serial_no"], data["challan_date"]):
        return {
            "status": "error",
            "message": "Duplicate challan: A record with the same BSR Code, Challan Number, and Date already exists."
        }

    row = {
        "challan_id": f"CH-{str(uuid.uuid4())[:8].upper()}",
        "quarter": data["quarter"],
        "financial_year": data["financial_year"],
        "bsr_code": str(data["bsr_code"]).strip(),
        "challan_serial_no": str(data["challan_serial_no"]).strip(),
        "challan_date": str(data["challan_date"]).strip(),
        "challan_amount": float(data["challan_amount"]),
        "section_code": data.get("section_code", "192"),
        "status": "ACTIVE"
    }

    append_row(CSV_CHALLANS, row)

    return {
        "status": "success",
        "message": f"Challan {row['challan_id']} saved successfully.",
        "challan_id": row["challan_id"]
    }


def edit_challan(challan_id, data):
    """
    Validate and update an existing challan. Returns dict with status/message.
    """
    # Check challan exists
    df = read_csv(CSV_CHALLANS)
    if df.empty:
        return {"status": "error", "message": "No challans found."}

    mask = df["challan_id"] == challan_id
    if not mask.any():
        return {"status": "error", "message": f"Challan '{challan_id}' not found."}

    # Field validation
    errors = validate_challan_fields(data)
    if errors:
        return {"status": "error", "message": "; ".join(errors)}

    # Duplicate check (exclude current record)
    if check_duplicate(data["bsr_code"], data["challan_serial_no"], data["challan_date"], exclude_id=challan_id):
        return {
            "status": "error",
            "message": "Duplicate challan: Another record with the same BSR Code, Challan Number, and Date already exists."
        }

    # Apply updates
    df.loc[mask, "quarter"] = data["quarter"]
    df.loc[mask, "financial_year"] = data["financial_year"]
    df.loc[mask, "bsr_code"] = str(data["bsr_code"]).strip()
    df.loc[mask, "challan_serial_no"] = str(data["challan_serial_no"]).strip()
    df.loc[mask, "challan_date"] = str(data["challan_date"]).strip()
    df.loc[mask, "challan_amount"] = float(data["challan_amount"])

    write_csv(CSV_CHALLANS, df)

    return {
        "status": "success",
        "message": f"Challan {challan_id} updated successfully."
    }


def delete_challan(challan_id):
    """Delete a challan by ID. Returns True if deleted, False if not found."""
    from app.base.utils.csv_service import delete_row
    return delete_row(CSV_CHALLANS, "challan_id", challan_id)


# ─────────────────────────────────────────────────────────────
# Legacy compatibility aliases
# ─────────────────────────────────────────────────────────────

def add_challan(
    challan_id,
    quarter,
    financial_year,
    bsr_code,
    challan_serial_no,
    challan_date,
    challan_amount,
    section_code="192"
):
    """Legacy add function – directly appends without validation."""
    row = {
        "challan_id": challan_id,
        "quarter": quarter,
        "financial_year": financial_year,
        "bsr_code": bsr_code,
        "challan_serial_no": challan_serial_no,
        "challan_date": challan_date,
        "challan_amount": challan_amount,
        "section_code": section_code,
        "status": "ACTIVE"
    }
    append_row(CSV_CHALLANS, row)
    return True


def update_challan(challan_id, updates):
    """Legacy update function using csv_service.update_row."""
    from app.base.utils.csv_service import update_row
    return update_row(CSV_CHALLANS, "challan_id", challan_id, updates)
