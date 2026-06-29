import io
import pandas as pd
from datetime import datetime

from config import CSV_PAYROLL, CSV_EMPLOYEES, CSV_PAYSLIPS, CSV_PAYROLL_BATCHES
from services.csv_service import read_csv

def get_payroll_register_data(filters: dict = None) -> list[dict]:
    if filters is None:
        filters = {}

    payroll_df = read_csv(CSV_PAYROLL)
    if payroll_df.empty:
        return []

    # Only include PROCESSED or LOCKED records
    valid_statuses = ["PROCESSED", "LOCKED"]
    if "payroll_status" in payroll_df.columns:
        payroll_df = payroll_df[payroll_df["payroll_status"].isin(valid_statuses)]
    else:
        return []

    # Apply filters
    fy = filters.get("fy")
    if fy:
        payroll_df = payroll_df[payroll_df["financial_year"] == fy]
        
    month = filters.get("month")
    if month:
        payroll_df = payroll_df[payroll_df["month"] == str(month)]
        
    batch_id = filters.get("batch_id")
    if batch_id:
        payroll_df = payroll_df[payroll_df["batch_id"] == batch_id]
        
    emp_id = filters.get("employee_id")
    if emp_id:
        # Case insensitive substring match
        payroll_df = payroll_df[payroll_df["employee_id"].str.contains(emp_id, case=False, na=False)]
        
    status = filters.get("payroll_status")
    if status:
        payroll_df = payroll_df[payroll_df["payroll_status"] == status]

    if payroll_df.empty:
        return []

    # Merge with Employees for Name, Dept, Desig
    employees_df = read_csv(CSV_EMPLOYEES)
    if not employees_df.empty:
        # Keep necessary columns
        emp_cols = ["employee_id", "name", "department", "designation", "pan", "uan", "pf_number", "esi_number", "bank_account", "ifsc_code"]
        available_cols = [c for c in emp_cols if c in employees_df.columns]
        payroll_df = pd.merge(payroll_df, employees_df[available_cols], on="employee_id", how="left")
    else:
        payroll_df["name"] = "Unknown"
        payroll_df["department"] = "N/A"
        payroll_df["designation"] = "N/A"

    # Merge with Batches for frequency
    batches_df = read_csv(CSV_PAYROLL_BATCHES)
    if not batches_df.empty and "batch_id" in batches_df.columns:
        batch_cols = ["batch_id", "payroll_frequency"]
        available_batch = [c for c in batch_cols if c in batches_df.columns]
        payroll_df = pd.merge(payroll_df, batches_df[available_batch], on="batch_id", how="left")
    else:
        payroll_df["payroll_frequency"] = "Monthly"

    # Merge with Payslips for payslip_status
    payslips_df = read_csv(CSV_PAYSLIPS)
    if not payslips_df.empty and "payroll_id" in payslips_df.columns:
        payslip_cols = ["payroll_id", "status"]
        payslips_subset = payslips_df[payslip_cols].rename(columns={"status": "payslip_status"})
        payroll_df = pd.merge(payroll_df, payslips_subset, on="payroll_id", how="left")
        payroll_df["payslip_status"] = payroll_df["payslip_status"].fillna("Not Generated")
    else:
        payroll_df["payslip_status"] = "Not Generated"

    # Fill NaNs for safety
    payroll_df = payroll_df.fillna("")

    # Department filter requires post-merge filtering
    dept = filters.get("department")
    if dept and "department" in payroll_df.columns:
        payroll_df = payroll_df[payroll_df["department"] == dept]

    # Convert to dict
    records = payroll_df.to_dict(orient="records")
    return records


def get_register_dashboard_stats(data: list[dict]) -> dict:
    stats = {
        "total_employees": len(set(r.get("employee_id") for r in data)),
        "total_gross": sum(float(r.get("gross_salary") or 0) for r in data),
        "total_net": sum(float(r.get("net_salary") or 0) for r in data),
        "total_deductions": 0,
        "total_employer_cost": sum(float(r.get("employer_cost") or 0) for r in data),
        "total_pf": sum(float(r.get("employee_pf", r.get("pf_employee", 0)) or 0) for r in data),
        "total_esi": sum(float(r.get("esi_employee", 0) or 0) for r in data),
        "total_tds": sum(float(r.get("tds", 0) or 0) for r in data),
    }
    
    stats["total_deductions"] = stats["total_gross"] - stats["total_net"]
    return stats


def export_to_excel(data: list[dict]) -> bytes:
    if not data:
        df = pd.DataFrame()
    else:
        df = pd.DataFrame(data)
        
    # Reorder/Rename columns for the export
    columns_mapping = {
        "batch_id": "Batch ID",
        "month": "Month",
        "financial_year": "Financial Year",
        "payroll_frequency": "Payroll Frequency",
        "employee_id": "Employee ID",
        "name": "Employee Name",
        "department": "Department",
        "designation": "Designation",
        
        # Hidden Export Fields
        "pan": "PAN",
        "uan": "UAN",
        "pf_number": "PF Number",
        "esi_number": "ESI Number",
        "bank_account": "Bank Account Number",
        "ifsc_code": "IFSC Code",
        
        "basic_salary": "Basic Salary",
        "gross_salary": "Gross Salary",
        
        # Placeholders
        "bonus": "Bonus",
        "overtime_amount": "Overtime",
        "lop_amount": "LOP Amount",
        
        "employee_pf": "Employee PF",
        "pf_employer": "Employer PF",
        "esi_employee": "Employee ESI",
        "esi_employer": "Employer ESI",
        "professional_tax": "Professional Tax",
        "lwf": "LWF",
        "tds": "TDS",
        
        "net_salary": "Net Salary",
        "employer_cost": "Total Employer Cost",
        "payroll_status": "Payroll Status",
        "payslip_status": "Payslip Status"
    }

    # Extract only available columns from mapping
    export_cols = []
    rename_dict = {}
    for k, v in columns_mapping.items():
        if k in df.columns:
            export_cols.append(k)
            rename_dict[k] = v
            
    df_export = df[export_cols].rename(columns=rename_dict)
    
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
        df_export.to_excel(writer, index=False, sheet_name="Payroll Register")
        
    return buffer.getvalue()


def export_to_csv(data: list[dict]) -> bytes:
    if not data:
        df = pd.DataFrame()
    else:
        df = pd.DataFrame(data)
        
    # Similar mapping to Excel
    columns_mapping = {
        "batch_id": "Batch ID",
        "month": "Month",
        "financial_year": "Financial Year",
        "payroll_frequency": "Payroll Frequency",
        "employee_id": "Employee ID",
        "name": "Employee Name",
        "department": "Department",
        "designation": "Designation",
        "pan": "PAN",
        "uan": "UAN",
        "pf_number": "PF Number",
        "esi_number": "ESI Number",
        "bank_account": "Bank Account Number",
        "ifsc_code": "IFSC Code",
        "basic_salary": "Basic Salary",
        "gross_salary": "Gross Salary",
        "bonus": "Bonus",
        "overtime_amount": "Overtime",
        "lop_amount": "LOP Amount",
        "employee_pf": "Employee PF",
        "pf_employer": "Employer PF",
        "esi_employee": "Employee ESI",
        "esi_employer": "Employer ESI",
        "professional_tax": "Professional Tax",
        "lwf": "LWF",
        "tds": "TDS",
        "net_salary": "Net Salary",
        "employer_cost": "Total Employer Cost",
        "payroll_status": "Payroll Status",
        "payslip_status": "Payslip Status"
    }
    
    export_cols = []
    rename_dict = {}
    for k, v in columns_mapping.items():
        if k in df.columns:
            export_cols.append(k)
            rename_dict[k] = v
            
    df_export = df[export_cols].rename(columns=rename_dict)
    
    buffer = io.BytesIO()
    df_export.to_csv(buffer, index=False)
    return buffer.getvalue()

def get_unique_departments() -> list[str]:
    df = read_csv(CSV_EMPLOYEES)
    if not df.empty and "department" in df.columns:
        return [d for d in df["department"].dropna().unique() if d]
    return []
