import pandas as pd
from datetime import datetime
import uuid

from config import CSV_FNF, CSV_EMPLOYEES, CSV_CONTRACTS, CURRENT_FY
from services.csv_service import read_csv, write_csv, append_row, read_csv_filtered
from services.contract_service import get_active_contract

def get_dashboard_stats(fy: str) -> dict:
    df = read_csv(CSV_FNF)
    if df.empty:
        return {"draft": 0, "review": 0, "approved": 0, "paid": 0, "total_amount": 0.0, "exits": 0}
        
    stats = {
        "draft": len(df[df["status"] == "Draft"]),
        "review": len(df[df["status"] == "Under Review"]),
        "approved": len(df[df["status"] == "Approved"]),
        "paid": len(df[df["status"] == "Paid"]),
        "total_amount": 0.0,
        "exits": len(df)
    }
    
    # Calculate amount from approved and paid
    valid = df[df["status"].isin(["Approved", "Paid"])]
    if not valid.empty:
        stats["total_amount"] = pd.to_numeric(valid["net_payable"], errors='coerce').fillna(0).sum()
        
    return stats


def get_all_settlements() -> list[dict]:
    df = read_csv(CSV_FNF)
    if df.empty:
        return []
        
    emp_df = read_csv(CSV_EMPLOYEES)
    if not emp_df.empty:
        df = pd.merge(df, emp_df[["employee_id", "name", "department"]], on="employee_id", how="left")
        
    return df.to_dict(orient="records")


def get_employee_settlements(employee_id: str) -> list[dict]:
    df = read_csv_filtered(CSV_FNF, "employee_id", employee_id)
    return df.to_dict(orient="records")


def calculate_fnf_components(employee_id: str, last_working_date: str) -> dict:
    """Calculates F&F components based on contract and provided LWD."""
    contract = get_active_contract(employee_id)
    if not contract:
        # Try to find the latest contract if no active one
        c_df = read_csv_filtered(CSV_CONTRACTS, "employee_id", employee_id)
        if not c_df.empty:
            contract = c_df.iloc[-1].to_dict()
            
    gross = float(contract.get("gross_salary", 0)) if contract else 0.0
    notice_days = int(contract.get("notice_period_days", 0)) if contract else 0
    
    # In a full system, we would compare LWD with last processed payroll month.
    # For now, we assume 15 days pending salary as an example of standard prorating.
    # We use 30-day month for all calculations as per plan.
    per_day_salary = gross / 30 if gross > 0 else 0
    
    # Dummy calculation for demo: 15 days pending, notice period deduction of 0
    pending_salary = round(per_day_salary * 15, 2)
    notice_amount = 0.0 
    
    # Placeholders
    leave_encashment = 0.0
    gratuity = 0.0
    bonus = 0.0
    recoveries = 0.0
    
    total_earnings = pending_salary + leave_encashment + gratuity + bonus
    total_deductions = recoveries + notice_amount
    net = total_earnings - total_deductions
    
    return {
        "pending_salary": pending_salary,
        "notice_period_amount": notice_amount,
        "leave_encashment": leave_encashment,
        "gratuity": gratuity,
        "bonus_incentives": bonus,
        "other_recoveries": recoveries,
        "total_earnings": total_earnings,
        "total_deductions": total_deductions,
        "net_payable": net
    }


def create_settlement(employee_id: str, lwd: str, user: str, overrides: dict = None) -> dict:
    df = read_csv_filtered(CSV_FNF, "employee_id", employee_id)
    # Check if active settlement exists
    if not df.empty:
        active = df[~df["status"].isin(["Cancelled", "Rejected"])]
        if not active.empty:
            return {"status": "error", "message": "An active settlement already exists for this employee."}
            
    if not overrides:
        calc = calculate_fnf_components(employee_id, lwd)
    else:
        # Recalculate totals if overrides provided
        pending = float(overrides.get("pending_salary", 0))
        leave = float(overrides.get("leave_encashment", 0))
        grat = float(overrides.get("gratuity", 0))
        bonus = float(overrides.get("bonus_incentives", 0))
        notice = float(overrides.get("notice_period_amount", 0))
        recov = float(overrides.get("other_recoveries", 0))
        
        te = pending + leave + grat + bonus
        td = notice + recov
        
        calc = {
            "pending_salary": pending,
            "notice_period_amount": notice,
            "leave_encashment": leave,
            "gratuity": grat,
            "bonus_incentives": bonus,
            "other_recoveries": recov,
            "total_earnings": te,
            "total_deductions": td,
            "net_payable": te - td
        }

    sid = f"FNF-{datetime.now().strftime('%Y%m')}-{str(uuid.uuid4())[:4].upper()}"
    
    new_record = {
        "settlement_id": sid,
        "employee_id": employee_id,
        "last_working_date": lwd,
        "status": "Draft",
        "remarks": overrides.get("remarks", "") if overrides else "",
        "created_by": user,
        "created_at": datetime.now().isoformat(),
        "approved_by": "",
        "approved_at": "",
        "paid_by": "",
        "paid_at": ""
    }
    new_record.update(calc)
    
    append_row(CSV_FNF, new_record)
    return {"status": "success", "message": "Draft settlement created successfully.", "settlement_id": sid}


def get_settlement_details(settlement_id: str) -> dict | None:
    df = read_csv_filtered(CSV_FNF, "settlement_id", settlement_id)
    if df.empty:
        return None
    
    fnf = df.iloc[0].to_dict()
    emp_id = fnf.get("employee_id")
    
    emp_df = read_csv_filtered(CSV_EMPLOYEES, "employee_id", emp_id)
    emp = emp_df.iloc[0].to_dict() if not emp_df.empty else {}
    
    contract = get_active_contract(emp_id)
    if not contract:
        c_df = read_csv_filtered(CSV_CONTRACTS, "employee_id", emp_id)
        if not c_df.empty:
            contract = c_df.iloc[-1].to_dict()
            
    return {
        "fnf": fnf,
        "employee": emp,
        "contract": contract
    }


def update_settlement_status(settlement_id: str, new_status: str, user: str) -> dict:
    df = read_csv(CSV_FNF)
    if df.empty or "settlement_id" not in df.columns:
        return {"status": "error", "message": "Settlement not found."}
        
    mask = df["settlement_id"] == settlement_id
    if not mask.any():
        return {"status": "error", "message": "Settlement not found."}
        
    idx = df.index[mask][0]
    current = df.at[idx, "status"]
    
    if current in ["Approved", "Paid"] and new_status in ["Draft", "Cancelled", "Rejected"]:
        return {"status": "error", "message": "Cannot modify an Approved or Paid settlement."}
        
    df.at[idx, "status"] = new_status
    _now = datetime.now().isoformat()
    
    if new_status == "Approved":
        df.at[idx, "approved_by"] = user
        df.at[idx, "approved_at"] = _now
    elif new_status == "Paid":
        df.at[idx, "paid_by"] = user
        df.at[idx, "paid_at"] = _now
        
    write_csv(CSV_FNF, df)
    return {"status": "success", "message": f"Settlement status updated to {new_status}."}
