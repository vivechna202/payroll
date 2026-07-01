"""
statutory_service.py – Business logic for statutory configurations and calculations.
Calculates PF, ESI, Professional Tax, and Labour Welfare Fund contributions.
"""

import uuid
import json
import pandas as pd
from datetime import datetime
from app.base.utils.config import CSV_STATUTORY_CONFIG, CSV_EMPLOYEES, CSV_DEDUCTOR_MASTER
from app.base.utils.csv_service import read_csv, write_csv, append_row, update_row, read_csv_filtered

def get_all_configs() -> list[dict]:
    df = read_csv(CSV_STATUTORY_CONFIG)
    if df.empty:
        return []
    configs = df.to_dict(orient="records")
    for c in configs:
        try:
            c["parameters"] = json.loads(c["parameters_json"])
        except:
            c["parameters"] = {}
    return configs

def get_config_by_id(config_id: str) -> dict | None:
    df = read_csv(CSV_STATUTORY_CONFIG)
    if df.empty or "config_id" not in df.columns:
        return None
    match = df[df["config_id"] == config_id]
    if match.empty:
        return None
    config = match.iloc[0].to_dict()
    try:
        config["parameters"] = json.loads(config["parameters_json"])
    except:
        config["parameters"] = {}
    return config

def create_config(rule_type: str, state: str, enabled: str, effective_from: str, parameters: dict) -> dict:
    df = read_csv(CSV_STATUTORY_CONFIG)
    # Check for duplicate config for same state, rule_type, and effective_from
    if not df.empty:
        mask = (df["rule_type"] == rule_type) & (df["state"] == state) & (df["effective_from"] == effective_from)
        if mask.any():
            return {"status": "error", "message": f"A configuration for {rule_type} in state '{state}' with effective date {effective_from} already exists."}

    config_id = f"STAT-{rule_type}-{str(uuid.uuid4())[:4].upper()}"
    _now = datetime.now().isoformat()
    row = {
        "config_id": config_id,
        "rule_type": rule_type,
        "state": state,
        "enabled": enabled,
        "effective_from": effective_from,
        "parameters_json": json.dumps(parameters),
        "created_at": _now,
        "updated_at": _now
    }
    append_row(CSV_STATUTORY_CONFIG, row)
    return {"status": "success", "message": "Statutory configuration created successfully.", "config_id": config_id}

def update_config(config_id: str, updates: dict) -> dict:
    df = read_csv(CSV_STATUTORY_CONFIG)
    if df.empty or "config_id" not in df.columns:
        return {"status": "error", "message": "Configuration not found."}
    mask = df["config_id"] == config_id
    if not mask.any():
        return {"status": "error", "message": "Configuration not found."}

    idx = df.index[mask][0]
    for k, v in updates.items():
        if k in df.columns:
            if k == "parameters_json" and isinstance(v, dict):
                df.at[idx, k] = json.dumps(v)
            else:
                df.at[idx, k] = str(v)
    df.at[idx, "updated_at"] = datetime.now().isoformat()
    write_csv(CSV_STATUTORY_CONFIG, df)
    return {"status": "success", "message": "Configuration updated successfully."}

def toggle_config(config_id: str) -> dict:
    config = get_config_by_id(config_id)
    if not config:
        return {"status": "error", "message": "Configuration not found."}
    new_status = "No" if config["enabled"] == "Yes" else "Yes"
    return update_config(config_id, {"enabled": new_status})

def get_employee_state(employee_id: str) -> str:
    emp_df = read_csv_filtered(CSV_EMPLOYEES, "employee_id", employee_id)
    if not emp_df.empty and "state" in emp_df.columns:
        state = emp_df.iloc[0].get("state", "").strip()
        if state:
            return state
    # Fallback to deductor_master state
    ded_df = read_csv(CSV_DEDUCTOR_MASTER)
    if not ded_df.empty and "state" in ded_df.columns:
        state = ded_df.iloc[0].get("state", "").strip()
        if state:
            return state
    return "Delhi"

def calculate_employee_statutory(employee_id: str, basic_salary: float, gross_salary: float, month: int, year: int, fy: str) -> dict:
    state = get_employee_state(employee_id)
    configs = get_all_configs()
    
    # Filter active enabled rules
    # Sort configs by effective_from desc to pick the latest applicable config
    configs = [c for c in configs if c["enabled"] == "Yes" and c["effective_from"] <= f"{year}-{month:02d}-01"]
    configs = sorted(configs, key=lambda x: x["effective_from"], reverse=True)

    # Initialize results
    res = {
        "pf_employee": 0.0,
        "pf_employer": 0.0,
        "pf_eps": 0.0,
        "pf_epf_employer": 0.0,
        "esi_employee": 0.0,
        "esi_employer": 0.0,
        "pt": 0.0,
        "lwf_employee": 0.0,
        "lwf_employer": 0.0
    }

    # 1. Evaluate PF Configuration
    pf_config = next((c for c in configs if c["rule_type"] == "PF"), None)
    if pf_config:
        params = pf_config["parameters"]
        emp_rate = float(params.get("employee_rate", 12.0))
        empr_rate = float(params.get("employer_rate", 12.0))
        eps_rate = float(params.get("eps_rate", 8.33))
        ceiling = float(params.get("wage_ceiling", 15000.0))
        respect_ceiling = params.get("respect_wage_ceiling", True)
        
        pf_wage = min(basic_salary, ceiling) if respect_ceiling else basic_salary
        
        # Calculate Employee PF
        res["pf_employee"] = round(pf_wage * emp_rate / 100.0, 2)
        # Calculate Employer PF (Total)
        res["pf_employer"] = round(pf_wage * empr_rate / 100.0, 2)
        
        if params.get("enable_eps_split", True):
            eps_wage = min(basic_salary, ceiling)
            res["pf_eps"] = round(eps_wage * eps_rate / 100.0, 2)
            res["pf_epf_employer"] = max(0.0, round(res["pf_employer"] - res["pf_eps"], 2))
        else:
            res["pf_eps"] = 0.0
            res["pf_epf_employer"] = res["pf_employer"]

    # 2. Evaluate ESI Configuration
    esi_config = next((c for c in configs if c["rule_type"] == "ESI"), None)
    if esi_config:
        params = esi_config["parameters"]
        ceiling = float(params.get("wage_ceiling", 21000.0))
        
        if gross_salary <= ceiling:
            emp_rate = float(params.get("employee_rate", 0.75))
            empr_rate = float(params.get("employer_rate", 3.25))
            res["esi_employee"] = round(gross_salary * emp_rate / 100.0, 2)
            res["esi_employer"] = round(gross_salary * empr_rate / 100.0, 2)

    # 3. Evaluate PT Configuration (State-wise)
    pt_config = next((c for c in configs if c["rule_type"] == "PT" and c["state"].lower() == state.lower()), None)
    if pt_config:
        params = pt_config["parameters"]
        slabs = params.get("slabs", [])
        for slab in slabs:
            min_val = float(slab.get("min", 0.0))
            max_val = float(slab.get("max", 99999999.0))
            if min_val <= gross_salary < max_val:
                amount = float(slab.get("amount", 0.0))
                # Check for February Maharashtra special rule
                if month == 2 and "feb_amount" in slab:
                    amount = float(slab["feb_amount"])
                res["pt"] = amount
                break

    # 4. Evaluate LWF Configuration (State-wise)
    lwf_config = next((c for c in configs if c["rule_type"] == "LWF" and c["state"].lower() == state.lower()), None)
    if lwf_config:
        params = lwf_config["parameters"]
        deduction_months = params.get("deduction_months", [])
        if month in deduction_months:
            res["lwf_employee"] = float(params.get("employee_contribution", 0.0))
            res["lwf_employer"] = float(params.get("employer_contribution", 0.0))

    return res
