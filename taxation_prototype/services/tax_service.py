"""
tax_service.py – Income tax & TDS calculation engine.

Phase 5: Monthly TDS computation.
"""

from datetime import datetime
import uuid
from config import (
    CSV_TDS, CSV_DECLARATIONS, CSV_DECLARATION_ITEMS, CSV_PROOFS, CSV_PAYROLL, CSV_EMPLOYEES,
    CURRENT_FY, STANDARD_DEDUCTION, TAX_SLABS_OLD, TAX_SLABS_NEW
)
from services.csv_service import read_csv, read_csv_filtered, csv_to_records, append_row

def calculate_tax(taxable_income: float, regime: str) -> float:
    slabs = TAX_SLABS_NEW if regime.upper() == "NEW" else TAX_SLABS_OLD
    tax = 0.0
    previous_limit = 0.0
    
    for slab in slabs:
        limit = slab["limit"]
        rate = slab["rate"]
        
        if taxable_income > previous_limit:
            taxable_amount_in_slab = min(taxable_income, limit) - previous_limit
            tax += taxable_amount_in_slab * rate
            previous_limit = limit
        else:
            break
            
    # Simple rebate under 87A: if income <= 7L (new) or 5L (old), tax is 0. 
    # For Phase 5 prototype, we just follow slabs. If needed, 87A rebate could be added here.
    if regime.upper() == "NEW" and taxable_income <= 700000:
        return 0.0
    if regime.upper() == "OLD" and taxable_income <= 500000:
        return 0.0
        
    return tax

def get_employee_tax_summary(employee_id: str, fy: str = CURRENT_FY) -> dict:
    tds_records = read_csv_filtered(CSV_TDS, "employee_id", employee_id)
    tds_records = tds_records[tds_records["financial_year"] == fy]
    
    payroll_records = read_csv_filtered(CSV_PAYROLL, "employee_id", employee_id)
    payroll_records = payroll_records[payroll_records["financial_year"] == fy]
    
    tds_deducted = 0
    gross_income = 0
    if not tds_records.empty:
        tds_deducted = tds_records["monthly_tds"].astype(float).sum()
    if not payroll_records.empty:
        gross_income = payroll_records["gross_salary"].astype(float).sum()
        
    latest_tds = tds_records.iloc[-1].to_dict() if not tds_records.empty else {}
    
    annual_tax = float(latest_tds.get("estimated_annual_tax", 0))
    remaining_tds = max(0, annual_tax - tds_deducted)
    
    # Get approved deductions summary
    proofs = csv_to_records(CSV_PROOFS)
    decl_items = csv_to_records(CSV_DECLARATION_ITEMS)
    decls = csv_to_records(CSV_DECLARATIONS)
    
    emp_decls = [d for d in decls if d["employee_id"] == employee_id and d["financial_year"] == fy and d["status"] == "SUBMITTED"]
    approved_deductions = []
    if emp_decls:
        decl = emp_decls[-1]
        d_id = decl["declaration_id"]
        items = [i for i in decl_items if i["declaration_id"] == d_id]
        for item in items:
            section = item["section"]
            amount = float(item["amount"])
            approved_proof = next((p for p in proofs if p["declaration_id"] == d_id and p["section"] == section and p["status"] == "APPROVED"), None)
            if approved_proof:
                approved_deductions.append({"section": section, "amount": amount})
        
    return {
        "employee_id": employee_id,
        "fy": fy,
        "gross_income": f"{gross_income:,.2f}",
        "standard_deduction": f"{STANDARD_DEDUCTION:,.2f}",
        "taxable_income": f"{float(latest_tds.get('annual_taxable_income', 0)):,.2f}",
        "tax_liability": f"{annual_tax:,.2f}",
        "tds_deducted_ytd": f"{tds_deducted:,.2f}",
        "remaining_tds": f"{remaining_tds:,.2f}",
        "regime": latest_tds.get("tax_regime", "NEW").upper(),
        "status": "active" if not tds_records.empty else "no_data",
        "monthly_tds_history": tds_records.to_dict(orient="records"),
        "approved_deductions": approved_deductions
    }

def get_monthly_tds_records(month: str = None, fy: str = None) -> list[dict]:
    df = read_csv(CSV_TDS)
    if month:
        df = df[df["month"] == str(month)]
    if fy:
        df = df[df["financial_year"] == fy]
    return df.to_dict(orient="records")

def compute_tds_for_month(month: str, fy: str) -> dict:
    payroll_df = read_csv(CSV_PAYROLL)
    mask = (payroll_df["month"] == str(month)) & (payroll_df["financial_year"] == fy)
    monthly_payroll = payroll_df[mask]
    
    if monthly_payroll.empty:
        return {"status": "error", "message": f"No processed payroll found for {month}/{fy}."}
        
    decls = csv_to_records(CSV_DECLARATIONS)
    decl_items = csv_to_records(CSV_DECLARATION_ITEMS)
    proofs = csv_to_records(CSV_PROOFS)
    
    tds_df = read_csv(CSV_TDS)
    
    processed_count = 0
    skipped_count = 0
    
    for _, pr in monthly_payroll.iterrows():
        emp_id = pr["employee_id"]
        
        # Check duplicate
        if not tds_df.empty and "employee_id" in tds_df.columns:
            tds_mask = (tds_df["employee_id"] == emp_id) & (tds_df["month"] == str(month)) & (tds_df["financial_year"] == fy)
            if tds_mask.any():
                skipped_count += 1
                continue
        
        # Find declaration
        emp_decls = [d for d in decls if d["employee_id"] == emp_id and d["financial_year"] == fy and d["status"] == "SUBMITTED"]
        decl = emp_decls[-1] if emp_decls else None
        
        regime = decl["tax_regime"] if decl else "NEW"
        
        annual_gross = float(pr["gross_salary"]) * 12
        annual_pf = float(pr["employee_pf"]) * 12
        annual_pt = float(pr["professional_tax"]) * 12
        
        deductions = STANDARD_DEDUCTION + annual_pt
        
        if regime.upper() == "OLD":
            deductions += annual_pf # PF is usually 80C
            if decl:
                d_id = decl["declaration_id"]
                items = [i for i in decl_items if i["declaration_id"] == d_id]
                for item in items:
                    # Check for approved proof
                    section = item["section"]
                    approved_proof = next((p for p in proofs if p["declaration_id"] == d_id and p["section"] == section and p["status"] == "APPROVED"), None)
                    if approved_proof:
                        deductions += float(item["amount"])
                        
        taxable_income = max(0, annual_gross - deductions)
        annual_tax = calculate_tax(taxable_income, regime)
        monthly_tds = annual_tax / 12.0
        
        row = {
            "tds_id": f"TDS-{str(uuid.uuid4())[:8].upper()}",
            "employee_id": emp_id,
            "financial_year": fy,
            "month": str(month),
            "tax_regime": regime.upper(),
            "annual_taxable_income": f"{taxable_income:.2f}",
            "estimated_annual_tax": f"{annual_tax:.2f}",
            "annual_tds": f"{annual_tax:.2f}",
            "monthly_tds": f"{monthly_tds:.2f}",
            "payroll_id": pr["payroll_id"],
            "calculated_at": datetime.now().isoformat()
        }
        
        append_row(CSV_TDS, row)
        processed_count += 1
        
    return {
        "status": "success",
        "message": f"TDS processed for {processed_count} employees. Skipped {skipped_count}."
    }

def get_tax_regime_comparison(employee_id: str, fy: str = CURRENT_FY) -> dict:
    payroll_df = read_csv_filtered(CSV_PAYROLL, "employee_id", employee_id)
    payroll_df = payroll_df[payroll_df["financial_year"] == fy]
    
    # We estimate annual gross based on latest month or sum if full year
    annual_gross = 0
    annual_pf = 0
    annual_pt = 0
    if not payroll_df.empty:
        latest = payroll_df.iloc[-1]
        annual_gross = float(latest["gross_salary"]) * 12
        annual_pf = float(latest["employee_pf"]) * 12
        annual_pt = float(latest["professional_tax"]) * 12
        
    decls = csv_to_records(CSV_DECLARATIONS)
    decl_items = csv_to_records(CSV_DECLARATION_ITEMS)
    proofs = csv_to_records(CSV_PROOFS)
    
    emp_decls = [d for d in decls if d["employee_id"] == employee_id and d["financial_year"] == fy and d["status"] == "SUBMITTED"]
    old_deductions = STANDARD_DEDUCTION + annual_pt + annual_pf
    
    if emp_decls:
        decl = emp_decls[-1]
        d_id = decl["declaration_id"]
        items = [i for i in decl_items if i["declaration_id"] == d_id]
        for item in items:
            section = item["section"]
            amount = float(item["amount"])
            approved_proof = next((p for p in proofs if p["declaration_id"] == d_id and p["section"] == section and p["status"] == "APPROVED"), None)
            if approved_proof:
                old_deductions += amount
                
    taxable_old = max(0, annual_gross - old_deductions)
    taxable_new = max(0, annual_gross - STANDARD_DEDUCTION - annual_pt)
    
    tax_old = calculate_tax(taxable_old, "OLD")
    tax_new = calculate_tax(taxable_new, "NEW")
    
    recommended = "NEW" if tax_new <= tax_old else "OLD"
    
    return {
        "employee_id": employee_id,
        "old_regime_tax": f"{tax_old:,.2f}",
        "new_regime_tax": f"{tax_new:,.2f}",
        "recommended": recommended,
        "status": "success" if not payroll_df.empty else "no_data"
    }

def get_hr_dashboard_metrics(fy: str = CURRENT_FY) -> dict:
    emps = csv_to_records(CSV_EMPLOYEES)
    active_emps = [e for e in emps if e.get("status") == "ACTIVE"]
    
    decls = csv_to_records(CSV_DECLARATIONS)
    proofs = csv_to_records(CSV_PROOFS)
    tds = csv_to_records(CSV_TDS)
    
    missing_declarations = []
    for emp in active_emps:
        emp_decls = [d for d in decls if d["employee_id"] == emp["employee_id"] and d["financial_year"] == fy]
        if not emp_decls:
            missing_declarations.append(emp)
            
    pending_proofs = []
    emp_with_pending_proofs = set()
    for p in proofs:
        if p["status"] == "PENDING":
            emp_with_pending_proofs.add(p["employee_id"])
    for emp in active_emps:
        if emp["employee_id"] in emp_with_pending_proofs:
            pending_proofs.append(emp)
            
    # For missing TDS, we just check if they have any TDS record for the current month.
    # To keep it simple, check if they have ANY tds record for the current month.
    today = datetime.today()
    current_month = str(today.month)
    missing_tds = []
    for emp in active_emps:
        emp_tds = [t for t in tds if t["employee_id"] == emp["employee_id"] and t["financial_year"] == fy and t["month"] == current_month]
        if not emp_tds:
            missing_tds.append(emp)
            
    return {
        "missing_declarations": missing_declarations,
        "pending_proofs": pending_proofs,
        "missing_tds": missing_tds,
        "current_month": current_month,
        "fy": fy
    }
