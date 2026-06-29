"""
structure_service.py – Business logic for Salary Structures.

Manages salary structure CRUD, component linking, and the
salary preview computation engine (Phase 2 – no payroll processing).
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import (
    CSV_SALARY_STRUCTURES,
    CSV_SALARY_COMPONENTS,
    CSV_STRUCTURE_COMPONENTS,
)
from services.csv_service import (
    read_csv, write_csv, append_row, update_row, delete_row, csv_to_records
)


# ─────────────────────────────────────────────────────────────
# Read helpers
# ─────────────────────────────────────────────────────────────

def get_all_structures(
    active_only: bool = False,
    search: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return all salary structures with their linked component count."""
    df = read_csv(CSV_SALARY_STRUCTURES)
    if df.empty:
        return []

    if active_only:
        df = df[df["active"] == "Yes"]
    if search:
        df = df[df["name"].str.lower().str.contains(search.lower(), na=False)]

    records = df.to_dict(orient="records")

    # Annotate each record with its component count
    sc_df = read_csv(CSV_STRUCTURE_COMPONENTS)
    for rec in records:
        sid = rec["structure_id"]
        if sc_df.empty or "structure_id" not in sc_df.columns:
            rec["component_count"] = 0
        else:
            rec["component_count"] = int((sc_df["structure_id"] == sid).sum())

    return records


def get_structure_by_id(structure_id: str) -> Optional[Dict[str, Any]]:
    """Return a single structure dict or None."""
    df = read_csv(CSV_SALARY_STRUCTURES)
    if df.empty or "structure_id" not in df.columns:
        return None
    match = df[df["structure_id"] == structure_id]
    if match.empty:
        return None
    rec = match.iloc[0].to_dict()
    # Annotate component count
    sc_df = read_csv(CSV_STRUCTURE_COMPONENTS)
    if sc_df.empty or "structure_id" not in sc_df.columns:
        rec["component_count"] = 0
    else:
        rec["component_count"] = int((sc_df["structure_id"] == structure_id).sum())
    return rec


def get_structure_components(structure_id: str) -> List[Dict[str, Any]]:
    """
    Return the full component detail rows for a structure,
    merged from structure_components + salary_components, sorted by sequence.
    """
    sc_df = read_csv(CSV_STRUCTURE_COMPONENTS)
    comp_df = read_csv(CSV_SALARY_COMPONENTS)

    if sc_df.empty or comp_df.empty:
        return []

    links = sc_df[sc_df["structure_id"] == structure_id]
    if links.empty:
        return []

    results = []
    for _, link in links.iterrows():
        cid = link["component_id"]
        comp_match = comp_df[comp_df["component_id"] == cid]
        if comp_match.empty:
            continue
        comp = comp_match.iloc[0].to_dict()
        # Merge override values
        if link.get("override_amount"):
            comp["effective_amount"] = link["override_amount"]
        elif link.get("override_percentage"):
            comp["effective_percentage"] = link["override_percentage"]
        comp["link_id"] = link["id"]
        results.append(comp)

    # Sort by sequence
    results.sort(key=lambda c: int(c.get("sequence", "9999")) if str(c.get("sequence", "9999")).isdigit() else 9999)
    return results


def get_structures_for_dropdown() -> List[Dict[str, str]]:
    """Return minimal list for use in select dropdowns."""
    df = read_csv(CSV_SALARY_STRUCTURES)
    if df.empty:
        return []
    active = df[df["active"] == "Yes"]
    return [
        {"structure_id": r["structure_id"], "name": r["name"]}
        for _, r in active.iterrows()
    ]


# ─────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────

def create_structure(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new salary structure."""
    name = data.get("name", "").strip()
    if not name:
        return {"status": "error", "message": "Structure name is required."}

    # Unique name check
    existing = read_csv(CSV_SALARY_STRUCTURES)
    if not existing.empty:
        if name.lower() in existing["name"].str.lower().tolist():
            return {"status": "error", "message": f"A salary structure named '{name}' already exists."}

    structure_type = data.get("structure_type", "Employee").strip()
    payroll_frequency = data.get("payroll_frequency", "Monthly").strip()

    now_iso = datetime.now().isoformat()
    structure_id = f"SS-{str(uuid.uuid4())[:6].upper()}"

    new_row = {
        "structure_id": structure_id,
        "name": name,
        "structure_type": structure_type,
        "payroll_frequency": payroll_frequency,
        "description": data.get("description", "").strip(),
        "active": "Yes",
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    append_row(CSV_SALARY_STRUCTURES, new_row)
    return {
        "status": "success",
        "message": f"Salary structure '{name}' created successfully.",
        "structure_id": structure_id,
    }


def update_structure(structure_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update salary structure metadata."""
    existing = get_structure_by_id(structure_id)
    if not existing:
        return {"status": "error", "message": "Structure not found."}

    name = data.get("name", existing["name"]).strip()
    if not name:
        return {"status": "error", "message": "Structure name is required."}

    # Unique name check (exclude self)
    all_df = read_csv(CSV_SALARY_STRUCTURES)
    if not all_df.empty:
        others = all_df[all_df["structure_id"] != structure_id]
        if name.lower() in others["name"].str.lower().tolist():
            return {"status": "error", "message": f"A structure named '{name}' already exists."}

    updates = {
        "name": name,
        "structure_type": data.get("structure_type", existing["structure_type"]).strip(),
        "payroll_frequency": data.get("payroll_frequency", existing["payroll_frequency"]).strip(),
        "description": data.get("description", existing.get("description", "")).strip(),
        "updated_at": datetime.now().isoformat(),
    }
    success = update_row(CSV_SALARY_STRUCTURES, "structure_id", structure_id, updates)
    if success:
        return {"status": "success", "message": f"Structure '{name}' updated."}
    return {"status": "error", "message": "Failed to update structure."}


def archive_structure(structure_id: str) -> Dict[str, Any]:
    """Set the structure to inactive (archived)."""
    existing = get_structure_by_id(structure_id)
    if not existing:
        return {"status": "error", "message": "Structure not found."}
    new_active = "No" if existing.get("active") == "Yes" else "Yes"
    update_row(CSV_SALARY_STRUCTURES, "structure_id", structure_id, {
        "active": new_active,
        "updated_at": datetime.now().isoformat(),
    })
    action = "archived" if new_active == "No" else "restored"
    return {"status": "success", "message": f"Structure {action} successfully.", "active": new_active}


# ─────────────────────────────────────────────────────────────
# Structure ↔ Component linking
# ─────────────────────────────────────────────────────────────

def add_component_to_structure(
    structure_id: str,
    component_id: str,
    override_amount: str = "",
    override_percentage: str = "",
) -> Dict[str, Any]:
    """Add a component to a structure. Blocks duplicates."""
    # Validate structure and component exist
    if not get_structure_by_id(structure_id):
        return {"status": "error", "message": "Salary structure not found."}

    from services.salary_component_service import get_component_by_id
    comp = get_component_by_id(component_id)
    if not comp:
        return {"status": "error", "message": "Salary component not found."}

    # Duplicate check
    sc_df = read_csv(CSV_STRUCTURE_COMPONENTS)
    if not sc_df.empty:
        dup = sc_df[
            (sc_df["structure_id"] == structure_id) &
            (sc_df["component_id"] == component_id)
        ]
        if not dup.empty:
            return {
                "status": "error",
                "message": f"'{comp['name']}' is already part of this structure.",
            }

    new_row = {
        "id": str(uuid.uuid4()),
        "structure_id": structure_id,
        "component_id": component_id,
        "override_amount": override_amount,
        "override_percentage": override_percentage,
        "added_at": datetime.now().isoformat(),
    }
    append_row(CSV_STRUCTURE_COMPONENTS, new_row)
    return {"status": "success", "message": f"'{comp['name']}' added to structure."}


def remove_component_from_structure(structure_id: str, component_id: str) -> Dict[str, Any]:
    """Remove a component from a structure."""
    sc_df = read_csv(CSV_STRUCTURE_COMPONENTS)
    if sc_df.empty:
        return {"status": "error", "message": "No links found."}

    mask = (sc_df["structure_id"] == structure_id) & (sc_df["component_id"] == component_id)
    if not mask.any():
        return {"status": "error", "message": "Component is not linked to this structure."}

    sc_df = sc_df[~mask].reset_index(drop=True)
    from services.csv_service import write_csv
    write_csv(CSV_STRUCTURE_COMPONENTS, sc_df)
    return {"status": "success", "message": "Component removed from structure."}


# ─────────────────────────────────────────────────────────────
# Salary Preview Engine
# ─────────────────────────────────────────────────────────────

def compute_preview(
    structure_id: str,
    basic_salary: float = 0.0,
    gross_override: float = 0.0,
    extra_inputs: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """
    Compute a salary preview for a given structure without running payroll.

    Algorithm:
    1. Load all components in sequence order.
    2. Build a mutable context dict seeded with BASIC (and optionally GROSS).
    3. Evaluate each component in sequence:
       - Fixed: use amount (or structure override)
       - Percentage: (pct/100) * context[percentage_of]
       - Formula: eval() in sandboxed context
    4. After computing all Earnings, update GROSS in context.
    5. Continue computing Deductions.
    6. Return structured breakdown.

    Returns dict with keys: earnings, deductions, gross, taxable, net, error
    """
    components = get_structure_components(structure_id)
    if not components:
        return {
            "error": "No components linked to this structure.",
            "earnings": [], "deductions": [], "gross": 0, "taxable": 0, "net": 0,
        }

    # ── Seed context ──────────────────────────────────────────
    context: Dict[str, float] = {
        "BASIC": float(basic_salary),
        "GROSS": float(gross_override) if gross_override else float(basic_salary),
        "NET": 0.0,
    }
    if extra_inputs:
        for k, v in extra_inputs.items():
            context[k.upper()] = float(v)

    # Pre-seed all component codes to 0
    for comp in components:
        context[comp["code"].upper()] = 0.0

    # ── Two-pass evaluation (earnings → then update GROSS → deductions) ──
    earnings_rows = []
    deductions_rows = []
    earnings_total = 0.0
    deductions_total = 0.0
    taxable_total = 0.0
    errors = []

    def _eval_component(comp: Dict[str, Any]) -> float:
        """Evaluate a single component's value and update context."""
        code = comp["code"].upper()
        ctype = comp.get("computation_type", "Fixed")

        # Use structure-level override if present
        eff_amount = comp.get("effective_amount", "")
        eff_pct = comp.get("effective_percentage", "")

        try:
            if ctype == "Fixed":
                val = float(eff_amount if eff_amount else (comp.get("amount") or 0))

            elif ctype == "Percentage":
                pct = float(eff_pct if eff_pct else (comp.get("percentage") or 0))
                pof = comp.get("percentage_of", "").upper()
                base = context.get(pof, 0.0)
                val = round((pct / 100.0) * base, 2)

            elif ctype == "Formula":
                formula = comp.get("formula", "0")
                # Safe eval: only context variables + safe builtins
                safe_builtins = {"round": round, "abs": abs, "min": min, "max": max, "int": int, "float": float}
                val = float(eval(  # noqa: S307
                    compile(formula, "<formula>", "eval"),
                    {"__builtins__": safe_builtins},
                    dict(context)
                ))
            else:
                val = 0.0

        except Exception as exc:
            errors.append(f"Error evaluating '{comp['name']}': {exc}")
            val = 0.0

        context[code] = round(val, 2)
        return round(val, 2)

    # Pass 1 – Earnings
    for comp in components:
        if comp.get("category") != "Earning":
            continue
        val = _eval_component(comp)
        earnings_total += val
        if comp.get("taxable") == "Yes":
            taxable_total += val
        earnings_rows.append({
            "name": comp["name"],
            "code": comp["code"].upper(),
            "category": "Earning",
            "computation_type": comp.get("computation_type"),
            "taxable": comp.get("taxable"),
            "amount": val,
        })

    # Update GROSS after earnings
    context["GROSS"] = round(earnings_total, 2)
    context["NET"] = round(earnings_total, 2)  # tentative before deductions

    # Pass 2 – Deductions
    for comp in components:
        if comp.get("category") != "Deduction":
            continue
        val = _eval_component(comp)
        deductions_total += val
        deductions_rows.append({
            "name": comp["name"],
            "code": comp["code"].upper(),
            "category": "Deduction",
            "computation_type": comp.get("computation_type"),
            "taxable": comp.get("taxable"),
            "amount": val,
        })

    net = round(earnings_total - deductions_total, 2)
    context["NET"] = net

    return {
        "earnings": earnings_rows,
        "deductions": deductions_rows,
        "gross": round(earnings_total, 2),
        "taxable": round(taxable_total, 2),
        "net": net,
        "deductions_total": round(deductions_total, 2),
        "basic": basic_salary,
        "errors": errors,
    }


# ─────────────────────────────────────────────────────────────
# Dashboard stats
# ─────────────────────────────────────────────────────────────

def get_structure_stats() -> Dict[str, int]:
    """Return dashboard stat counts for salary structures."""
    df = read_csv(CSV_SALARY_STRUCTURES)
    sc_df = read_csv(CSV_STRUCTURE_COMPONENTS)

    if df.empty:
        return {"total": 0, "active": 0, "archived": 0, "total_components": 0}

    return {
        "total": len(df),
        "active": int((df["active"] == "Yes").sum()),
        "archived": int((df["active"] == "No").sum()),
        "total_components": 0 if sc_df.empty else len(sc_df),
    }
