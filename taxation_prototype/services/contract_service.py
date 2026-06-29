"""
contract_service.py – Business logic for the Employee Contracts module.
Provides functions for CRUD operations on contracts, pagination, search,
filtering, and business validation rules.
"""

import os
import uuid
from datetime import datetime
import pandas as pd
from typing import Optional, List, Dict, Any

from config import CSV_CONTRACTS, CSV_EMPLOYEES
from services.csv_service import read_csv, write_csv, append_row, update_row, read_csv_filtered

def get_all_contracts(search: Optional[str] = None, 
                      status_filter: Optional[str] = None, 
                      type_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Return all contracts as a list of dicts, optionally filtered by search query, status, and type.
    """
    df = read_csv(CSV_CONTRACTS)
    if df.empty:
        return []
        
    # Apply filters
    if status_filter:
        df = df[df["status"] == status_filter]
        
    if type_filter:
        df = df[df["salary_structure_type"] == type_filter]
        
    if search:
        search_lower = search.lower().strip()
        df = df[
            df["employee_name"].str.lower().str.contains(search_lower) |
            df["employee_id"].str.lower().str.contains(search_lower) |
            df["contract_id"].str.lower().str.contains(search_lower)
        ]
        
    # Sort by created_at descending
    if not df.empty and "created_at" in df.columns:
        df = df.sort_values(by="created_at", ascending=False)
        
    return df.to_dict(orient="records")

def get_contract_by_id(contract_id: str) -> Optional[Dict[str, Any]]:
    """Return the contract details for a specific contract ID."""
    df = read_csv(CSV_CONTRACTS)
    if df.empty or "contract_id" not in df.columns:
        return None
    match = df[df["contract_id"] == contract_id]
    if match.empty:
        return None
    return match.iloc[0].to_dict()

def get_contracts_for_employee(employee_id: str) -> List[Dict[str, Any]]:
    """Return all contracts for a specific employee, sorted by start date / created_at descending."""
    df = read_csv_filtered(CSV_CONTRACTS, "employee_id", employee_id)
    if df.empty:
        return []
    # Sort: we want active/running or latest contracts first
    df["sort_date"] = pd.to_datetime(df["contract_start_date"], errors="coerce")
    df = df.sort_values(by=["sort_date", "created_at"], ascending=[False, False])
    df = df.drop(columns=["sort_date"])
    return df.to_dict(orient="records")

def get_active_contract(employee_id: str) -> Optional[Dict[str, Any]]:
    """Return the active (Running) contract for an employee, if any."""
    contracts = get_contracts_for_employee(employee_id)
    for c in contracts:
        if c.get("status") == "Running":
            return c
    return None

def create_contract(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new contract with proper validations.
    """
    # 1. Fetch employee details
    employee_id = data.get("employee_id", "").strip()
    emp_df = read_csv_filtered(CSV_EMPLOYEES, "employee_id", employee_id)
    if emp_df.empty:
        return {"status": "error", "message": f"Employee with ID {employee_id} not found."}
    
    emp = emp_df.iloc[0].to_dict()
    
    # 2. Extract and validate dates
    start_date_str = data.get("contract_start_date", "").strip()
    end_date_str = data.get("contract_end_date", "").strip()
    
    if not start_date_str:
        return {"status": "error", "message": "Contract start date is required."}
        
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        return {"status": "error", "message": "Invalid start date format. Use YYYY-MM-DD."}
        
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            if end_date < start_date:
                return {"status": "error", "message": "Contract end date cannot be before start date."}
        except ValueError:
            return {"status": "error", "message": "Invalid end date format. Use YYYY-MM-DD."}
            
    # 3. Check status and check for other active contracts if this one is "Running"
    status = data.get("status", "Draft").strip()
    if status not in ["Draft", "Running", "Expired", "Terminated"]:
        status = "Draft"
        
    if status == "Running":
        active_contract = get_active_contract(employee_id)
        if active_contract:
            return {
                "status": "error", 
                "message": f"Employee {emp['name']} already has an active contract ({active_contract['contract_id']}). "
                           f"Deactivate the current active contract before creating a new active one."
            }
            
    # 4. Assemble the row
    contract_id = f"CON-{str(uuid.uuid4())[:8].upper()}"
    now_iso = datetime.now().isoformat()
    
    new_contract = {
        "contract_id": contract_id,
        "employee_id": employee_id,
        "employee_name": emp.get("name", ""),
        "department": emp.get("department", ""),
        "designation": emp.get("designation", ""),
        "company": data.get("company", "TaxPro Corp").strip(),
        "joining_date": emp.get("date_of_joining", ""),
        "contract_start_date": start_date_str,
        "contract_end_date": end_date_str,
        "salary_structure": data.get("salary_structure", "").strip(),
        "salary_structure_type": data.get("salary_structure_type", "Permanent").strip(),
        "work_schedule": data.get("work_schedule", "Standard 40 Hours/Week").strip(),
        "payroll_frequency": "Monthly",
        "currency": data.get("currency", "INR").strip(),
        "basic_salary": str(data.get("basic_salary", "0")),
        "gross_salary": str(data.get("gross_salary", "0")),
        "status": status,
        "created_at": now_iso,
        "updated_at": now_iso
    }
    
    append_row(CSV_CONTRACTS, new_contract)
    return {"status": "success", "message": "Contract created successfully.", "contract_id": contract_id}

def update_contract(contract_id: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update an existing contract with proper validations.
    """
    # 1. Check if contract exists
    contract = get_contract_by_id(contract_id)
    if not contract:
        return {"status": "error", "message": f"Contract with ID {contract_id} not found."}
        
    employee_id = contract["employee_id"]
    
    # 2. Extract and validate dates
    start_date_str = updates.get("contract_start_date", contract["contract_start_date"]).strip()
    end_date_str = updates.get("contract_end_date", contract["contract_end_date"]).strip()
    
    if not start_date_str:
        return {"status": "error", "message": "Contract start date is required."}
        
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    except ValueError:
        return {"status": "error", "message": "Invalid start date format. Use YYYY-MM-DD."}
        
    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
            if end_date < start_date:
                return {"status": "error", "message": "Contract end date cannot be before start date."}
        except ValueError:
            return {"status": "error", "message": "Invalid end date format. Use YYYY-MM-DD."}
            
    # 3. Check status validation
    status = updates.get("status", contract["status"]).strip()
    if status not in ["Draft", "Running", "Expired", "Terminated"]:
        status = contract["status"]
        
    # If status is changing to "Running", make sure no other contract is Running
    if status == "Running" and contract["status"] != "Running":
        active_contract = get_active_contract(employee_id)
        if active_contract:
            return {
                "status": "error", 
                "message": f"Employee already has an active contract ({active_contract['contract_id']}). "
                           f"Deactivate the current active contract before activating this one."
            }
            
    # 4. Prepare updates dictionary
    now_iso = datetime.now().isoformat()
    fields_to_update = {
        "company": updates.get("company", contract["company"]).strip(),
        "contract_start_date": start_date_str,
        "contract_end_date": end_date_str,
        "salary_structure": updates.get("salary_structure", contract["salary_structure"]).strip(),
        "salary_structure_type": updates.get("salary_structure_type", contract["salary_structure_type"]).strip(),
        "work_schedule": updates.get("work_schedule", contract["work_schedule"]).strip(),
        "currency": updates.get("currency", contract["currency"]).strip(),
        "basic_salary": str(updates.get("basic_salary", contract["basic_salary"])),
        "gross_salary": str(updates.get("gross_salary", contract["gross_salary"])),
        "status": status,
        "updated_at": now_iso
    }
    
    success = update_row(CSV_CONTRACTS, "contract_id", contract_id, fields_to_update)
    if success:
        return {"status": "success", "message": "Contract updated successfully."}
    else:
        return {"status": "error", "message": "Failed to update contract in database."}

def set_contract_status(contract_id: str, new_status: str) -> Dict[str, Any]:
    """
    Directly transition the status of a contract (e.g. from Draft to Running).
    """
    if new_status not in ["Draft", "Running", "Expired", "Terminated"]:
        return {"status": "error", "message": f"Invalid contract status: {new_status}"}
        
    contract = get_contract_by_id(contract_id)
    if not contract:
        return {"status": "error", "message": f"Contract with ID {contract_id} not found."}
        
    # If activating, check active contract count
    if new_status == "Running" and contract["status"] != "Running":
        active_contract = get_active_contract(contract["employee_id"])
        if active_contract:
            return {
                "status": "error",
                "message": f"Employee already has an active contract ({active_contract['contract_id']}). "
                           f"Deactivate the current active contract before activating this one."
            }
            
    now_iso = datetime.now().isoformat()
    success = update_row(CSV_CONTRACTS, "contract_id", contract_id, {
        "status": new_status,
        "updated_at": now_iso
    })
    
    if success:
        return {"status": "success", "message": f"Contract status updated to {new_status}."}
    else:
        return {"status": "error", "message": "Failed to update contract status."}
