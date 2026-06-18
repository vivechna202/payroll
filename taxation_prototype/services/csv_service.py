"""
csv_service.py – Generic CSV read / write utilities using pandas.

Phase 1: All data lives in flat CSV files under dummy_data/.
Phase 2 Integration Point: Replace these functions with SQLAlchemy ORM
                           queries backed by PostgreSQL. The callers in
                           payroll_service, tax_service, etc. should need
                           only minimal changes because they interact with
                           DataFrames, which can be recreated from DB rows.
"""

import os
import pandas as pd
from typing import Optional


# ─────────────────────────────────────────────────────────────
# Read helpers
# ─────────────────────────────────────────────────────────────

def read_csv(filepath: str) -> pd.DataFrame:
    """Return the full CSV as a DataFrame. Returns empty DF if file missing."""
    if not os.path.exists(filepath):
        return pd.DataFrame()
    return pd.read_csv(filepath, dtype=str).fillna("")


def read_csv_filtered(filepath: str, column: str, value: str) -> pd.DataFrame:
    """Return rows where *column* equals *value*."""
    df = read_csv(filepath)
    if df.empty or column not in df.columns:
        return pd.DataFrame()
    return df[df[column] == value].reset_index(drop=True)


def read_csv_row(filepath: str, column: str, value: str) -> Optional[dict]:
    """Return the first matching row as a dict, or None."""
    df = read_csv_filtered(filepath, column, value)
    if df.empty:
        return None
    return df.iloc[0].to_dict()


# ─────────────────────────────────────────────────────────────
# Write helpers
# ─────────────────────────────────────────────────────────────

def write_csv(filepath: str, df: pd.DataFrame) -> None:
    """Overwrite the CSV with *df*. Creates directories if needed."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    df.to_csv(filepath, index=False)


def append_row(filepath: str, row: dict) -> None:
    """Append a single dict row to an existing CSV."""
    df = read_csv(filepath)
    new_row = pd.DataFrame([row])
    df = pd.concat([df, new_row], ignore_index=True)
    write_csv(filepath, df)


def update_row(filepath: str, key_column: str, key_value: str, updates: dict) -> bool:
    """
    Find the first row where key_column == key_value and apply *updates*.
    Returns True if a row was found and updated.
    """
    df = read_csv(filepath)
    if df.empty or key_column not in df.columns:
        return False
    mask = df[key_column] == key_value
    if not mask.any():
        return False
    for col, val in updates.items():
        if col in df.columns:
            df.loc[mask, col] = val
    write_csv(filepath, df)
    return True


def delete_row(filepath: str, key_column: str, key_value: str) -> bool:
    """Delete rows where key_column == key_value. Returns True if rows removed."""
    df = read_csv(filepath)
    if df.empty or key_column not in df.columns:
        return False
    before = len(df)
    df = df[df[key_column] != key_value].reset_index(drop=True)
    if len(df) == before:
        return False
    write_csv(filepath, df)
    return True


# ─────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────

def csv_to_records(filepath: str) -> list[dict]:
    """Return all rows as a list of dicts (for template rendering)."""
    df = read_csv(filepath)
    return df.to_dict(orient="records")


def ensure_csv(filepath: str, columns: list[str]) -> None:
    """Create the CSV with headers only if it does not exist yet."""
    if not os.path.exists(filepath):
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        pd.DataFrame(columns=columns).to_csv(filepath, index=False)

# ─────────────────────────────────────────────────────────────
# Phase 2: Declaration Specific Methods
# ─────────────────────────────────────────────────────────────

def is_declaration_window_open(fy: str) -> bool:
    from config import CSV_DECLARATION_WINDOWS
    from datetime import date
    df = read_csv(CSV_DECLARATION_WINDOWS)
    if df.empty:
        return False
    today = date.today().isoformat()
    active = df[(df["fy"] == fy) & (df["status"] == "ACTIVE")]
    for _, row in active.iterrows():
        start = row.get("start_date", "")
        end = row.get("end_date", "")
        if start and end and start <= today <= end:
            return True
    return False

def create_declaration(emp_id: str, fy: str, regime: str, items: dict, status: str) -> str:
    import uuid
    from datetime import datetime
    from config import CSV_DECLARATIONS, CSV_DECLARATION_ITEMS
    decl_id = f"DEC-{str(uuid.uuid4())[:8].upper()}"
    now = datetime.now().isoformat()
    
    decl_row = {
        "declaration_id": decl_id,
        "employee_id": emp_id,
        "financial_year": fy,
        "tax_regime": regime,
        "status": status,
        "submitted_at": now if status == "SUBMITTED" else "",
        "updated_at": now
    }
    append_row(CSV_DECLARATIONS, decl_row)
    
    if items:
        df_items = read_csv(CSV_DECLARATION_ITEMS)
        new_items = [{"declaration_id": decl_id, "section": k, "amount": v} for k, v in items.items()]
        df_items = pd.concat([df_items, pd.DataFrame(new_items)], ignore_index=True)
        write_csv(CSV_DECLARATION_ITEMS, df_items)
        
    return decl_id

def update_declaration(decl_id: str, regime: str, items: dict, status: str) -> bool:
    from datetime import datetime
    from config import CSV_DECLARATIONS, CSV_DECLARATION_ITEMS
    now = datetime.now().isoformat()
    updates = {
        "tax_regime": regime,
        "status": status,
        "updated_at": now
    }
    if status == "SUBMITTED":
        updates["submitted_at"] = now
        
    if not update_row(CSV_DECLARATIONS, "declaration_id", decl_id, updates):
        return False
        
    df_items = read_csv(CSV_DECLARATION_ITEMS)
    if not df_items.empty and "declaration_id" in df_items.columns:
        df_items = df_items[df_items["declaration_id"] != decl_id]
    if items:
        new_items = [{"declaration_id": decl_id, "section": k, "amount": v} for k, v in items.items()]
        df_items = pd.concat([df_items, pd.DataFrame(new_items)], ignore_index=True)
    write_csv(CSV_DECLARATION_ITEMS, df_items)
    
    return True

def get_employee_declarations(emp_id: str) -> list[dict]:
    from config import CSV_DECLARATIONS
    df = read_csv_filtered(CSV_DECLARATIONS, "employee_id", emp_id)
    return df.to_dict(orient="records")

def get_declaration_items(decl_id: str) -> dict:
    from config import CSV_DECLARATION_ITEMS
    df = read_csv_filtered(CSV_DECLARATION_ITEMS, "declaration_id", decl_id)
    if df.empty:
        return {}
    return dict(zip(df["section"], df["amount"]))

def get_all_declarations() -> list[dict]:
    from config import CSV_DECLARATIONS
    df = read_csv(CSV_DECLARATIONS)
    return df.to_dict(orient="records")

