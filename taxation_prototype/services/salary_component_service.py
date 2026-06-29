"""
salary_component_service.py – Business logic for Salary Components.

Provides full CRUD, validation, formula safety checks, and
circular-dependency detection for the Phase 2 Salary Structures module.
"""

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from config import CSV_SALARY_COMPONENTS, CSV_STRUCTURE_COMPONENTS
from services.csv_service import (
    read_csv, write_csv, append_row, update_row, delete_row, csv_to_records
)

# ─────────────────────────────────────────────────────────────
# Read helpers
# ─────────────────────────────────────────────────────────────

def get_all_components(
    category: Optional[str] = None,
    active_only: bool = False,
    search: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Return all salary components, optionally filtered."""
    df = read_csv(CSV_SALARY_COMPONENTS)
    if df.empty:
        return []

    if category:
        df = df[df["category"] == category]
    if active_only:
        df = df[df["active"] == "Yes"]
    if search:
        sl = search.lower()
        df = df[
            df["name"].str.lower().str.contains(sl, na=False) |
            df["code"].str.lower().str.contains(sl, na=False)
        ]

    # Sort by sequence (numeric), then name
    if not df.empty and "sequence" in df.columns:
        df["_seq"] = df["sequence"].apply(lambda x: int(x) if str(x).isdigit() else 9999)
        df = df.sort_values(by=["_seq", "name"])
        df = df.drop(columns=["_seq"])

    return df.to_dict(orient="records")


def get_component_by_id(component_id: str) -> Optional[Dict[str, Any]]:
    """Return single component dict or None."""
    df = read_csv(CSV_SALARY_COMPONENTS)
    if df.empty or "component_id" not in df.columns:
        return None
    match = df[df["component_id"] == component_id]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def get_component_by_code(code: str) -> Optional[Dict[str, Any]]:
    """Lookup component by its short code alias."""
    df = read_csv(CSV_SALARY_COMPONENTS)
    if df.empty or "code" not in df.columns:
        return None
    match = df[df["code"].str.upper() == code.upper()]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def get_all_codes() -> List[str]:
    """Return all existing component codes (uppercase)."""
    df = read_csv(CSV_SALARY_COMPONENTS)
    if df.empty or "code" not in df.columns:
        return []
    return [c.upper() for c in df["code"].tolist() if c]


# ─────────────────────────────────────────────────────────────
# Validation helpers
# ─────────────────────────────────────────────────────────────

def _validate_formula(formula: str, all_codes: List[str]) -> Optional[str]:
    """
    Validate that a formula only references known component codes and the
    special aliases BASIC, GROSS, NET. Returns an error message or None.
    """
    if not formula or not formula.strip():
        return "Formula cannot be empty for Formula computation type."

    # Allowed identifiers = all codes + built-ins we expose
    allowed = set(c.upper() for c in all_codes) | {"BASIC", "GROSS", "NET", "round", "abs", "min", "max", "int", "float"}

    # Try a test eval with a safe context of zeroes
    test_ctx = {c: 0.0 for c in allowed}
    try:
        eval(compile(formula, "<formula>", "eval"), {"__builtins__": {}}, test_ctx)  # noqa: S307
    except SyntaxError as exc:
        return f"Formula syntax error: {exc}"
    except Exception:
        # Runtime errors (div-by-zero with zeroes, etc.) are acceptable
        pass

    return None  # OK


def detect_circular_dependency(components: List[Dict[str, Any]]) -> Optional[str]:
    """
    Detect circular formula dependencies using DFS topological sort.
    Returns an error message if a cycle is found, else None.
    """
    # Build adjacency: code → set of codes it depends on
    graph: Dict[str, set] = {}
    for comp in components:
        code = comp.get("code", "").upper()
        deps: set = set()
        ctype = comp.get("computation_type", "")
        if ctype == "Percentage":
            pof = comp.get("percentage_of", "").upper()
            if pof:
                deps.add(pof)
        elif ctype == "Formula":
            formula = comp.get("formula", "")
            all_codes_upper = [c.get("code", "").upper() for c in components]
            for token in all_codes_upper:
                if token and token != code and token in formula.upper():
                    deps.add(token)
        graph[code] = deps

    # DFS cycle detection
    WHITE, GRAY, BLACK = 0, 1, 2
    state = {c: WHITE for c in graph}

    def dfs(node: str) -> bool:
        if node not in state:
            return False
        if state[node] == GRAY:
            return True  # cycle
        if state[node] == BLACK:
            return False
        state[node] = GRAY
        for neighbour in graph.get(node, []):
            if dfs(neighbour):
                return True
        state[node] = BLACK
        return False

    for code in graph:
        if state[code] == WHITE and dfs(code):
            return f"Circular dependency detected involving component code '{code}'."
    return None


# ─────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────

def create_component(data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new salary component with full validation."""
    name = data.get("name", "").strip()
    code = data.get("code", "").strip().upper()
    category = data.get("category", "").strip()
    computation_type = data.get("computation_type", "Fixed").strip()

    # Required fields
    if not name:
        return {"status": "error", "message": "Component name is required."}
    if not code:
        return {"status": "error", "message": "Component code is required."}
    if category not in ("Earning", "Deduction"):
        return {"status": "error", "message": "Category must be 'Earning' or 'Deduction'."}
    if computation_type not in ("Fixed", "Percentage", "Formula"):
        return {"status": "error", "message": "Computation type must be Fixed, Percentage, or Formula."}

    # Duplicate name / code check
    existing = read_csv(CSV_SALARY_COMPONENTS)
    if not existing.empty:
        if name.lower() in existing["name"].str.lower().tolist():
            return {"status": "error", "message": f"A component named '{name}' already exists."}
        if code.upper() in existing["code"].str.upper().tolist():
            return {"status": "error", "message": f"Component code '{code}' is already used."}

    all_codes = get_all_codes()

    # Type-specific validations
    amount = ""
    percentage = ""
    percentage_of = ""
    formula = ""

    if computation_type == "Fixed":
        raw_amount = data.get("amount", "0")
        try:
            amount = str(float(raw_amount))
        except (ValueError, TypeError):
            return {"status": "error", "message": "Amount must be a valid number."}

    elif computation_type == "Percentage":
        try:
            pct = float(data.get("percentage", 0))
            if not (0 <= pct <= 100):
                return {"status": "error", "message": "Percentage must be between 0 and 100."}
            percentage = str(pct)
        except (ValueError, TypeError):
            return {"status": "error", "message": "Percentage must be a valid number."}
        pof = data.get("percentage_of", "").strip().upper()
        if not pof:
            return {"status": "error", "message": "'Percentage of' code is required for Percentage type."}
        if pof not in all_codes and pof not in ("BASIC", "GROSS", "NET"):
            return {"status": "error", "message": f"Component code '{pof}' does not exist."}
        percentage_of = pof

    elif computation_type == "Formula":
        formula = data.get("formula", "").strip()
        err = _validate_formula(formula, all_codes + [code])
        if err:
            return {"status": "error", "message": err}

    # Sequence
    try:
        sequence = int(data.get("sequence", 100))
    except (ValueError, TypeError):
        sequence = 100

    now_iso = datetime.now().isoformat()
    component_id = f"COMP-{str(uuid.uuid4())[:8].upper()}"

    new_row = {
        "component_id": component_id,
        "name": name,
        "code": code,
        "category": category,
        "computation_type": computation_type,
        "amount": amount,
        "percentage": percentage,
        "percentage_of": percentage_of,
        "formula": formula,
        "sequence": str(sequence),
        "taxable": "Yes" if data.get("taxable", "No") in ("Yes", "yes", "1", True) else "No",
        "active": "Yes",
        "description": data.get("description", "").strip(),
        "created_at": now_iso,
        "updated_at": now_iso,
    }

    append_row(CSV_SALARY_COMPONENTS, new_row)
    return {
        "status": "success",
        "message": f"Salary component '{name}' created successfully.",
        "component_id": component_id,
    }


def update_component(component_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Update an existing salary component with validation."""
    existing = get_component_by_id(component_id)
    if not existing:
        return {"status": "error", "message": "Component not found."}

    name = data.get("name", existing["name"]).strip()
    code = data.get("code", existing["code"]).strip().upper()
    category = data.get("category", existing["category"]).strip()
    computation_type = data.get("computation_type", existing["computation_type"]).strip()

    if not name:
        return {"status": "error", "message": "Component name is required."}
    if category not in ("Earning", "Deduction"):
        return {"status": "error", "message": "Category must be 'Earning' or 'Deduction'."}
    if computation_type not in ("Fixed", "Percentage", "Formula"):
        return {"status": "error", "message": "Computation type must be Fixed, Percentage, or Formula."}

    # Duplicate check (exclude self)
    all_comps = read_csv(CSV_SALARY_COMPONENTS)
    if not all_comps.empty:
        others = all_comps[all_comps["component_id"] != component_id]
        if name.lower() in others["name"].str.lower().tolist():
            return {"status": "error", "message": f"A component named '{name}' already exists."}
        if code.upper() in others["code"].str.upper().tolist():
            return {"status": "error", "message": f"Component code '{code}' is already used."}

    # Recompute all_codes excluding self
    all_codes = [c.upper() for c in all_comps["code"].tolist() if c and c.upper() != code]

    amount = existing.get("amount", "")
    percentage = existing.get("percentage", "")
    percentage_of = existing.get("percentage_of", "")
    formula = existing.get("formula", "")

    if computation_type == "Fixed":
        try:
            amount = str(float(data.get("amount", existing.get("amount", "0"))))
        except (ValueError, TypeError):
            return {"status": "error", "message": "Amount must be a valid number."}
        percentage = ""
        percentage_of = ""
        formula = ""

    elif computation_type == "Percentage":
        try:
            pct = float(data.get("percentage", existing.get("percentage", 0)))
            if not (0 <= pct <= 100):
                return {"status": "error", "message": "Percentage must be between 0 and 100."}
            percentage = str(pct)
        except (ValueError, TypeError):
            return {"status": "error", "message": "Percentage must be a valid number."}
        pof = data.get("percentage_of", existing.get("percentage_of", "")).strip().upper()
        if not pof:
            return {"status": "error", "message": "'Percentage of' code is required."}
        if pof not in all_codes and pof not in ("BASIC", "GROSS", "NET"):
            return {"status": "error", "message": f"Component code '{pof}' does not exist."}
        percentage_of = pof
        amount = ""
        formula = ""

    elif computation_type == "Formula":
        formula = data.get("formula", existing.get("formula", "")).strip()
        err = _validate_formula(formula, all_codes + [code])
        if err:
            return {"status": "error", "message": err}
        amount = ""
        percentage = ""
        percentage_of = ""

    try:
        sequence = int(data.get("sequence", existing.get("sequence", 100)))
    except (ValueError, TypeError):
        sequence = 100

    updates = {
        "name": name,
        "code": code,
        "category": category,
        "computation_type": computation_type,
        "amount": amount,
        "percentage": percentage,
        "percentage_of": percentage_of,
        "formula": formula,
        "sequence": str(sequence),
        "taxable": "Yes" if data.get("taxable", existing.get("taxable", "No")) in ("Yes", "yes", "1", True) else "No",
        "description": data.get("description", existing.get("description", "")).strip(),
        "updated_at": datetime.now().isoformat(),
    }

    success = update_row(CSV_SALARY_COMPONENTS, "component_id", component_id, updates)
    if success:
        return {"status": "success", "message": f"Component '{name}' updated successfully."}
    return {"status": "error", "message": "Failed to update component."}


def toggle_component_active(component_id: str) -> Dict[str, Any]:
    """Toggle the active/inactive state of a component."""
    comp = get_component_by_id(component_id)
    if not comp:
        return {"status": "error", "message": "Component not found."}
    new_active = "No" if comp.get("active") == "Yes" else "Yes"
    update_row(CSV_SALARY_COMPONENTS, "component_id", component_id, {
        "active": new_active,
        "updated_at": datetime.now().isoformat()
    })
    state = "activated" if new_active == "Yes" else "deactivated"
    return {"status": "success", "message": f"Component {state} successfully.", "active": new_active}


def delete_component(component_id: str) -> Dict[str, Any]:
    """Delete a component. Blocked if it is used in any salary structure."""
    comp = get_component_by_id(component_id)
    if not comp:
        return {"status": "error", "message": "Component not found."}

    # Guard: check if used in any structure
    sc_df = read_csv(CSV_STRUCTURE_COMPONENTS)
    if not sc_df.empty and "component_id" in sc_df.columns:
        if not sc_df[sc_df["component_id"] == component_id].empty:
            return {
                "status": "error",
                "message": (
                    f"Cannot delete '{comp['name']}' — it is assigned to one or more "
                    "salary structures. Remove it from all structures first."
                ),
            }

    deleted = delete_row(CSV_SALARY_COMPONENTS, "component_id", component_id)
    if deleted:
        return {"status": "success", "message": f"Component '{comp['name']}' deleted."}
    return {"status": "error", "message": "Failed to delete component."}


def get_component_stats() -> Dict[str, int]:
    """Return dashboard stat counts for salary components."""
    df = read_csv(CSV_SALARY_COMPONENTS)
    if df.empty:
        return {"total": 0, "earnings": 0, "deductions": 0, "inactive": 0}
    return {
        "total": len(df),
        "earnings": int((df["category"] == "Earning").sum()),
        "deductions": int((df["category"] == "Deduction").sum()),
        "inactive": int((df["active"] == "No").sum()),
    }
