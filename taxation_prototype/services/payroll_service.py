"""
payroll_service.py – Payroll calculation engine.

Phase 4: Functional processing for base salaries, PF, PT, and net pay.
"""

from datetime import datetime
import uuid
import pandas as pd
from config import CSV_PAYROLL, CSV_EMPLOYEES, CSV_EMPLOYEE_SALARY, PF_PERCENTAGE, PROFESSIONAL_TAX
from services.csv_service import read_csv, read_csv_filtered, csv_to_records, append_row, update_row, write_csv

def get_employee_salary(employee_id: str) -> dict:
    """Return the current salary breakdown for an employee."""
    df = read_csv_filtered(CSV_EMPLOYEE_SALARY, "employee_id", employee_id)
    if df.empty:
        return {}
    return df.iloc[-1].to_dict()

def get_all_employee_salaries() -> list[dict]:
    """Return all active employees with their salary data joined."""
    emps = csv_to_records(CSV_EMPLOYEES)
    sals = csv_to_records(CSV_EMPLOYEE_SALARY)
    
    sal_map = {s["employee_id"]: s for s in sals}
    active_emps = []
    for e in emps:
        if e.get("status") == "ACTIVE":
            s = sal_map.get(e["employee_id"], {})
            e["basic_salary"] = s.get("basic_salary", "0")
            e["hra"] = s.get("hra", "0")
            e["special_allowance"] = s.get("special_allowance", "0")
            e["other_allowances"] = s.get("other_allowances", "0")
            try:
                e["gross_monthly"] = float(e["basic_salary"]) + float(e["hra"]) + float(e["special_allowance"]) + float(e["other_allowances"])
            except:
                e["gross_monthly"] = 0
            active_emps.append(e)
    return active_emps

def update_employee_salary(employee_id: str, basic: float, hra: float, special: float, other: float) -> bool:
    """Update base salary parameters for an employee."""
    from datetime import date
    df = read_csv(CSV_EMPLOYEE_SALARY)
    mask = df["employee_id"] == employee_id
    if mask.any():
        idx = df.index[mask][0]
        df.at[idx, "basic_salary"] = basic
        df.at[idx, "hra"] = hra
        df.at[idx, "special_allowance"] = special
        df.at[idx, "other_allowances"] = other
        write_csv(CSV_EMPLOYEE_SALARY, df)
        return True
    else:
        append_row(CSV_EMPLOYEE_SALARY, {
            "employee_id": employee_id,
            "basic_salary": basic,
            "hra": hra,
            "special_allowance": special,
            "other_allowances": other,
            "effective_from": date.today().isoformat()
        })
        return True

def get_all_payroll_records() -> list[dict]:
    return csv_to_records(CSV_PAYROLL)

def get_employee_payroll(employee_id: str) -> list[dict]:
    df = read_csv_filtered(CSV_PAYROLL, "employee_id", employee_id)
    return df.to_dict(orient="records")

def process_monthly_payroll(month: str, fy: str) -> dict:
    emps = csv_to_records(CSV_EMPLOYEES)
    sals = csv_to_records(CSV_EMPLOYEE_SALARY)
    sal_map = {s["employee_id"]: s for s in sals}
    
    payroll_df = read_csv(CSV_PAYROLL)
    
    processed_count = 0
    skipped_count = 0
    
    for e in emps:
        if e.get("status") != "ACTIVE":
            continue
            
        emp_id = e["employee_id"]
        
        # Check if already processed
        if not payroll_df.empty and "employee_id" in payroll_df.columns:
            mask = (payroll_df["employee_id"] == emp_id) & (payroll_df["month"] == str(month)) & (payroll_df["financial_year"] == fy)
            if mask.any():
                skipped_count += 1
                continue
                
        # Get salary info
        sal = sal_map.get(emp_id)
        if not sal:
            continue
            
        basic = float(sal.get("basic_salary") or 0)
        hra = float(sal.get("hra") or 0)
        special = float(sal.get("special_allowance") or 0)
        other = float(sal.get("other_allowances") or 0)
        
        gross = basic + hra + special + other
        pf = basic * (PF_PERCENTAGE / 100.0)
        pt = PROFESSIONAL_TAX
        net = gross - pf - pt
        
        row = {
            "payroll_id": f"PAY-{str(uuid.uuid4())[:8].upper()}",
            "employee_id": emp_id,
            "financial_year": fy,
            "month": str(month),
            "basic_salary": f"{basic:.2f}",
            "hra": f"{hra:.2f}",
            "special_allowance": f"{special:.2f}",
            "other_allowances": f"{other:.2f}",
            "gross_salary": f"{gross:.2f}",
            "employee_pf": f"{pf:.2f}",
            "professional_tax": f"{pt:.2f}",
            "net_salary": f"{net:.2f}",
            "payroll_status": "PROCESSED",
            "processed_at": datetime.now().isoformat()
        }
        append_row(CSV_PAYROLL, row)
        if payroll_df.empty:
            payroll_df = pd.DataFrame([row])
        else:
            payroll_df = pd.concat([payroll_df, pd.DataFrame([row])], ignore_index=True)
        processed_count += 1

    return {
        "status": "success",
        "message": f"Processed {processed_count} employees. Skipped {skipped_count} (already processed).",
        "month": month,
        "fy": fy,
    }

def get_payroll_summary(month: str, fy: str) -> dict:
    df = read_csv(CSV_PAYROLL)
    if df.empty or "month" not in df.columns:
        return {
            "total_gross": 0, "total_deductions": 0, "total_net": 0,
            "total_tds": 0, "employee_count": 0, "month": month, "fy": fy
        }
        
    mask = (df["month"] == str(month)) & (df["financial_year"] == fy)
    f_df = df[mask]
    
    if f_df.empty:
        return {
            "total_gross": 0, "total_deductions": 0, "total_net": 0,
            "total_tds": 0, "employee_count": 0, "month": month, "fy": fy
        }
        
    gross = pd.to_numeric(f_df["gross_salary"]).sum()
    pf = pd.to_numeric(f_df["employee_pf"]).sum()
    pt = pd.to_numeric(f_df["professional_tax"]).sum()
    net = pd.to_numeric(f_df["net_salary"]).sum()
    count = len(f_df)
    
    return {
        "total_gross": f"{gross:,.2f}",
        "total_deductions": f"{(pf+pt):,.2f}",
        "total_net": f"{net:,.2f}",
        "total_tds": "0.00", # Phase 4 out of scope
        "employee_count": count,
        "month": month,
        "fy": fy,
    }
