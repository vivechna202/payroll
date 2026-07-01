"""
ess_service.py – Business logic for Employee Self Service (ESS) & Manager Self Service (MSS).
Read-only view aggregator for profiles, dashboards, team overview, and placeholder modules.
"""

import os
import pandas as pd
from datetime import datetime
from app.base.utils.config import CSV_EMPLOYEES, CSV_CONTRACTS, CSV_PAYROLL, CSV_PAYSLIPS, CSV_FNF, CURRENT_FY
from app.base.utils.csv_service import read_csv, read_csv_filtered
from app.payroll.services.contract_service import get_active_contract
from app.payroll.services.payslip_service import get_employee_payslips
from app.payroll.services.fnf_service import get_employee_settlements

# Define manager-to-employee mapping (Sneha Iyer EMP003 manages these)
TEAM_MAPPING = {
    "EMP003": ["EMP001", "EMP002", "EMP004", "EMP005"]
}

def get_managed_employees(manager_id: str) -> list[str]:
    """Returns the list of employee IDs reporting to the manager."""
    return TEAM_MAPPING.get(manager_id, [])

def is_manager(employee_id: str) -> bool:
    """Returns True if the employee is registered as a manager."""
    return employee_id in TEAM_MAPPING

def get_employee_dashboard_metrics(employee_id: str) -> dict:
    """Retrieve dashboard KPI metrics for the employee."""
    # Current Salary (Gross) from active contract
    contract = get_active_contract(employee_id)
    gross_salary = float(contract.get("gross_salary", 0)) if contract else 0.0
    
    # Latest Payslip
    payslips = get_employee_payslips(employee_id)
    latest_payslip = payslips[0] if payslips else None
    
    # Active Contract ID
    contract_status = "Active" if contract else "None"
    contract_id = contract.get("contract_id", "N/A") if contract else "N/A"
    
    # Tax regime from employee salary mapping
    from app.base.utils.config import CSV_EMPLOYEE_SALARY
    sal_df = read_csv_filtered(CSV_EMPLOYEE_SALARY, "employee_id", employee_id)
    tax_regime = sal_df.iloc[-1].get("tds_regime", "NEW") if not sal_df.empty else "NEW"
    
    # Pending declarations
    from app.base.utils.config import CSV_DECLARATIONS
    decl_df = read_csv_filtered(CSV_DECLARATIONS, "employee_id", employee_id)
    pending_decls = len(decl_df[decl_df["status"] == "DRAFT"]) if not decl_df.empty else 0
    
    # Investment proof status
    from app.base.utils.config import CSV_PROOFS
    proof_df = read_csv_filtered(CSV_PROOFS, "employee_id", employee_id)
    proof_status = "Pending Action"
    if not proof_df.empty:
        pending_proofs = len(proof_df[proof_df["status"] == "PENDING"])
        if pending_proofs == 0:
            proof_status = "Verified"
        else:
            proof_status = f"{pending_proofs} Under Review"
    else:
        proof_status = "Not Submitted"
        
    return {
        "gross_salary": gross_salary,
        "latest_payslip_id": latest_payslip.get("payslip_id") if latest_payslip else "N/A",
        "latest_payslip_amount": float(latest_payslip.get("net_salary", 0)) if latest_payslip else 0.0,
        "contract_status": contract_status,
        "contract_id": contract_id,
        "tax_regime": tax_regime,
        "pending_declarations": pending_decls,
        "investment_proof_status": proof_status
    }

def get_manager_dashboard_metrics(manager_id: str) -> dict:
    """Retrieve dashboard KPI metrics for the manager's team."""
    managed_ids = get_managed_employees(manager_id)
    team_size = len(managed_ids)
    
    # Filter active employees
    emp_df = read_csv(CSV_EMPLOYEES)
    active_count = 0
    if not emp_df.empty and team_size > 0:
        active_count = len(emp_df[(emp_df["employee_id"].isin(managed_ids)) & (emp_df["status"] == "ACTIVE")])
        
    # Pending approvals for declarations/proofs for team members
    from app.base.utils.config import CSV_PROOFS
    proof_df = read_csv(CSV_PROOFS)
    pending_approvals = 0
    if not proof_df.empty and team_size > 0:
        pending_approvals = len(proof_df[(proof_df["employee_id"].isin(managed_ids)) & (proof_df["status"] == "PENDING")])
        
    # Total processed payroll count for team
    payroll_df = read_csv(CSV_PAYROLL)
    processed_count = 0
    if not payroll_df.empty and team_size > 0:
        processed_count = len(payroll_df[(payroll_df["employee_id"].isin(managed_ids)) & (payroll_df["payroll_status"].isin(["PROCESSED", "LOCKED"]))])
        
    # Expiring contracts (soon is < 30 days)
    contract_df = read_csv(CSV_CONTRACTS)
    expiring_soon = 0
    if not contract_df.empty and team_size > 0:
        team_contracts = contract_df[contract_df["employee_id"].isin(managed_ids)]
        for _, row in team_contracts.iterrows():
            end_date = row.get("end_date", "")
            if end_date:
                try:
                    days_left = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.now()).days
                    if 0 <= days_left <= 30:
                        expiring_soon += 1
                except ValueError:
                    pass
                    
    return {
        "team_size": team_size,
        "active_employees": active_count,
        "pending_approvals": pending_approvals,
        "payroll_processed": processed_count,
        "contracts_expiring_soon": expiring_soon
    }

def get_team_members(manager_id: str) -> list[dict]:
    """Retrieve detailed profiles of team members."""
    managed_ids = get_managed_employees(manager_id)
    emp_df = read_csv(CSV_EMPLOYEES)
    if emp_df.empty or not managed_ids:
        return []
        
    team_df = emp_df[emp_df["employee_id"].isin(managed_ids)]
    
    # Join with contracts
    contracts_df = read_csv(CSV_CONTRACTS)
    team_records = []
    
    for _, emp in team_df.iterrows():
        emp_id = emp["employee_id"]
        record = emp.to_dict()
        
        # Get active contract
        act_contract = None
        if not contracts_df.empty:
            c_subset = contracts_df[(contracts_df["employee_id"] == emp_id) & (contracts_df["status"] == "active")]
            if not c_subset.empty:
                act_contract = c_subset.iloc[-1].to_dict()
        
        record["active_contract"] = act_contract
        team_records.append(record)
        
    return team_records

def get_team_payroll_overview(manager_id: str) -> list[dict]:
    """Retrieve team payroll summary for overview."""
    managed_ids = get_managed_employees(manager_id)
    payroll_df = read_csv(CSV_PAYROLL)
    if payroll_df.empty or not managed_ids:
        return []
        
    team_payroll = payroll_df[payroll_df["employee_id"].isin(managed_ids)]
    emp_df = read_csv(CSV_EMPLOYEES)
    
    # Merge for employee name
    if not emp_df.empty:
        team_payroll = pd.merge(team_payroll, emp_df[["employee_id", "name", "department"]], on="employee_id", how="left")
        
    return team_payroll.fillna("").to_dict(orient="records")

def get_employee_notifications(employee_id: str) -> list[dict]:
    """Generate dynamic notifications for the employee."""
    notifications = []
    
    # 1. Tax declaration status
    from app.base.utils.config import CSV_DECLARATIONS
    decl_df = read_csv_filtered(CSV_DECLARATIONS, "employee_id", employee_id)
    if not decl_df.empty:
        latest_decl = decl_df.iloc[-1]
        if latest_decl["status"] == "DRAFT":
            notifications.append({
                "id": 1,
                "type": "warning",
                "message": "Your investment declaration is in Draft. Please submit it.",
                "date": latest_decl.get("updated_at", datetime.now().isoformat())[:10]
            })
            
    # 2. Latest Payslip notification
    payslips = get_employee_payslips(employee_id)
    if payslips:
        latest = payslips[0]
        notifications.append({
            "id": 2,
            "type": "info",
            "message": f"Payslip for period {latest.get('month')}/{latest.get('financial_year')} has been generated with status {latest.get('status')}.",
            "date": latest.get("created_at", datetime.now().isoformat())[:10]
        })
        
    # 3. Contract active notification
    contract = get_active_contract(employee_id)
    if contract:
        notifications.append({
            "id": 3,
            "type": "success",
            "message": f"Your employment contract ({contract.get('contract_id')}) is currently active.",
            "date": contract.get("start_date", datetime.now().isoformat())[:10]
        })
        
    return notifications

def get_employee_documents(employee_id: str) -> list[dict]:
    """Retrieve list of generated/uploaded employee documents."""
    documents = []
    
    # 1. Active Contract Document
    contract = get_active_contract(employee_id)
    if contract:
        documents.append({
            "name": f"Employment Contract - {contract.get('contract_id')}.pdf",
            "type": "Contract",
            "date": contract.get("start_date", "N/A"),
            "source": "HR Generated"
        })
        
    # 2. Form 16 Approved PDF Documents
    from app.base.utils.config import CSV_FORM16_APPROVED
    f16_df = read_csv(CSV_FORM16_APPROVED)
    if not f16_df.empty and "employee_id" in f16_df.columns:
        emp_f16 = f16_df[f16_df["employee_id"] == employee_id]
        for _, row in emp_f16.iterrows():
            documents.append({
                "name": row.get("pdf_filename", "Form16.pdf"),
                "type": "Form 16 Tax Document",
                "date": row.get("approved_at", "N/A")[:10],
                "source": "Approved Form 16"
            })
            
    # 3. Full & Final Settlement (if any exits)
    fnfs = get_employee_settlements(employee_id)
    for fnf in fnfs:
        documents.append({
            "name": f"Exit Settlement Statement - {fnf.get('settlement_id')}.pdf",
            "type": "Full & Final Settlement",
            "date": fnf.get("last_working_date", "N/A"),
            "source": f"FnF Status: {fnf.get('status')}"
        })
        
    return documents
