import pandas as pd
import uuid
from config import CSV_CHALLANS
from services.csv_service import read_csv, append_row, write_csv


def get_all_challans():
    """Return all challans."""
    df = read_csv(CSV_CHALLANS)
    if df.empty:
        return []
    return df.to_dict(orient="records")


def get_challans_by_quarter(quarter, fy):
    """Return challans for a quarter."""
    df = read_csv(CSV_CHALLANS)

    if df.empty:
        return []

    df = df[
        (df["quarter"] == quarter) &
        (df["financial_year"] == fy)
    ]

    return df.to_dict(orient="records")


def get_quarter_challans(quarter, fy):
    """Return challans for a quarter (alias)."""
    return get_challans_by_quarter(quarter, fy)



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
    """Add new challan."""

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


def get_challan(challan_id):
    """Get single challan."""

    df = read_csv(CSV_CHALLANS)

    if df.empty:
        return None

    row = df[df["challan_id"] == challan_id]

    if row.empty:
        return None

    return row.iloc[0].to_dict()


def update_challan(challan_id, updates):
    """Update an existing challan by ID."""
    from services.csv_service import update_row
    return update_row(CSV_CHALLANS, "challan_id", challan_id, updates)


def delete_challan(challan_id):
    """Delete a challan by ID."""
    from services.csv_service import delete_row
    return delete_row(CSV_CHALLANS, "challan_id", challan_id)

def save_challan(data):
    row = {
        "challan_id": f"CH-{str(uuid.uuid4())[:8].upper()}",
        "quarter": data["quarter"],
        "financial_year": data["financial_year"],
        "bsr_code": data["bsr_code"],
        "challan_serial_no": data["challan_serial_no"],
        "challan_date": data["challan_date"],
        "challan_amount": data["challan_amount"],
        "section_code": data.get("section_code", "192"),
        "status": "ACTIVE"
    }

    append_row(CSV_CHALLANS, row)

    return {
        "status": "success",
        "message": "Challan saved successfully"
    }

def edit_challan(challan_id, data):
    challans = read_csv(CSV_CHALLANS)

    if challans.empty:
        return {
            "status": "error",
            "message": "No challans found"
        }

    mask = challans["challan_id"] == challan_id
    if not mask.any():
        return {
            "status": "error",
            "message": "Challan not found"
        }

    challans.loc[mask, "quarter"] = data["quarter"]
    challans.loc[mask, "financial_year"] = data["financial_year"]
    challans.loc[mask, "bsr_code"] = data["bsr_code"]
    challans.loc[mask, "challan_serial_no"] = data["challan_serial_no"]
    challans.loc[mask, "challan_date"] = data["challan_date"]
    challans.loc[mask, "challan_amount"] = data["challan_amount"]

    write_csv(CSV_CHALLANS, challans)

    return {
        "status": "success",
        "message": "Challan updated successfully"
    }
