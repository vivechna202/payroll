"""
tax_service.py – Income tax & TDS calculation engine.

Enhanced with complete Indian TDS calculation for both OLD and NEW tax regimes.
"""

from datetime import datetime
import uuid
import pandas as pd
from config import (
    CSV_TDS, CSV_DECLARATIONS, CSV_DECLARATION_ITEMS, CSV_PROOFS, CSV_PAYROLL, CSV_EMPLOYEES,
    CSV_EMPLOYEE_SALARY, CURRENT_FY, STANDARD_DEDUCTION, TAX_SLABS_OLD, TAX_SLABS_NEW,
    PF_PERCENTAGE, PROFESSIONAL_TAX
)
from services.csv_service import read_csv, read_csv_filtered, csv_to_records, append_row


def apply_old_regime_slabs(taxable_income: float) -> float:
    """
    Apply OLD tax regime slabs to taxable income.
    
    Old Regime Slabs (FY 2024-25):
    - 0 - 2.5L: 0%
    - 2.5L - 5L: 5%
    - 5L - 10L: 20%
    - Above 10L: 30%
    
    Includes rebate under Section 87A: If taxable income <= 5L, tax is zero
    """
    if taxable_income <= 250000:
        return 0.0
    
    tax = 0.0
    
    # 2.5L to 5L at 5%
    if taxable_income > 250000:
        slab_amount = min(taxable_income, 500000) - 250000
        tax += slab_amount * 0.05
    
    # 5L to 10L at 20%
    if taxable_income > 500000:
        slab_amount = min(taxable_income, 1000000) - 500000
        tax += slab_amount * 0.20
    
    # Above 10L at 30%
    if taxable_income > 1000000:
        slab_amount = taxable_income - 1000000
        tax += slab_amount * 0.30
    
    # Section 87A Rebate: If taxable income <= 5L, tax is zero
    if taxable_income <= 500000:
        tax = 0.0
    
    return tax


def apply_new_regime_slabs(taxable_income: float) -> float:
    """
    Apply NEW tax regime slabs to taxable income.
    
    New Regime Slabs (FY 2024-25):
    - 0 - 3L: 0%
    - 3L - 6L: 5%
    - 6L - 9L: 10%
    - 9L - 12L: 15%
    - 12L - 15L: 20%
    - Above 15L: 30%
    
    Includes rebate under Section 87A: If taxable income <= 7L, tax is zero
    """
    if taxable_income <= 300000:
        return 0.0
    
    tax = 0.0
    
    # 3L to 6L at 5%
    if taxable_income > 300000:
        slab_amount = min(taxable_income, 600000) - 300000
        tax += slab_amount * 0.05
    
    # 6L to 9L at 10%
    if taxable_income > 600000:
        slab_amount = min(taxable_income, 900000) - 600000
        tax += slab_amount * 0.10
    
    # 9L to 12L at 15%
    if taxable_income > 900000:
        slab_amount = min(taxable_income, 1200000) - 900000
        tax += slab_amount * 0.15
    
    # 12L to 15L at 20%
    if taxable_income > 1200000:
        slab_amount = min(taxable_income, 1500000) - 1200000
        tax += slab_amount * 0.20
    
    # Above 15L at 30%
    if taxable_income > 1500000:
        slab_amount = taxable_income - 1500000
        tax += slab_amount * 0.30
    
    # Section 87A Rebate: If taxable income <= 7L, tax is zero
    if taxable_income <= 700000:
        tax = 0.0
    
    return tax


def apply_cess(tax: float) -> float:
    """
    Apply 4% Health and Education Cess on tax amount.
    """
    return tax * 0.04


def calculate_taxable_income(annual_income: float, regime: str, deductions: dict) -> float:
    """
    Calculate taxable income based on regime and deductions.
    
    Args:
        annual_income: Annual gross income
        regime: "OLD" or "NEW"
        deductions: Dictionary containing deduction amounts
            - section_80C: Deduction under Section 80C (max 1.5L)
            - section_80D: Deduction under Section 80D (health insurance)
            - hra_exemption: HRA exemption amount
            - pf_contribution: PF contribution (for old regime)
    
    Returns:
        Taxable income after applicable deductions
    """
    regime = regime.upper() if regime else "NEW"
    
    # Standard deduction applies to both regimes
    total_deductions = STANDARD_DEDUCTION
    
    if regime == "OLD":
        # Old regime: Allow most deductions
        section_80c = min(float(deductions.get("section_80C", 0)), 150000)  # Max 1.5L
        section_80d = float(deductions.get("section_80D", 0))
        hra_exemption = float(deductions.get("hra_exemption", 0))
        pf_contribution = float(deductions.get("pf_contribution", 0))
        
        total_deductions += section_80c + section_80d + hra_exemption + pf_contribution
    else:
        # New regime: Only standard deduction (most exemptions removed)
        # No additional deductions in new regime
        pass
    
    taxable_income = max(0, annual_income - total_deductions)
    return taxable_income


def calculate_tds(monthly_gross: float, regime: str, employee_deductions: dict) -> float:
    """
    Calculate monthly TDS based on gross salary, tax regime, and deductions.
    
    Args:
        monthly_gross: Monthly gross salary
        regime: "OLD" or "NEW" tax regime
        employee_deductions: Dictionary containing deduction amounts
            - section_80C: Deduction under Section 80C
            - section_80D: Deduction under Section 80D  
            - hra_exemption: HRA exemption amount
            - basic_salary: Basic salary amount (for PF calculation)
    
    Returns:
        Monthly TDS amount (annual TDS / 12)
    """
    regime = regime.upper() if regime else "NEW"
    
    # Calculate annual gross
    annual_gross = monthly_gross * 12
    
    # Add PF contribution for deduction calculation (12% of basic)
    basic_salary = float(employee_deductions.get("basic_salary", 0))
    pf_contribution = basic_salary * (PF_PERCENTAGE / 100.0) * 12  # Annual PF
    
    # Prepare deductions dictionary
    deductions = {
        "section_80C": employee_deductions.get("section_80C", 0),
        "section_80D": employee_deductions.get("section_80D", 0),
        "hra_exemption": employee_deductions.get("hra_exemption", 0),
        "pf_contribution": pf_contribution
    }
    
    # Calculate taxable income
    taxable_income = calculate_taxable_income(annual_gross, regime, deductions)
    
    # Calculate tax based on regime
    if regime == "OLD":
        tax = apply_old_regime_slabs(taxable_income)
    else:
        tax = apply_new_regime_slabs(taxable_income)
    
    # Apply 4% health and education cess
    tax_with_cess = tax + apply_cess(tax)
    
    # Return monthly TDS
    monthly_tds = tax_with_cess / 12.0
    
    return round(monthly_tds, 2)


# Legacy functions for backward compatibility
def calculate_tax(taxable_income: float, regime: str) -> float:
    """
    Legacy function - use calculate_tds() for new implementations.
    Calculate tax based on taxable income and regime.
    """
    regime = regime.upper() if regime else "NEW"
    if regime == "OLD":
        return apply_old_regime_slabs(taxable_income)
    else:
        return apply_new_regime_slabs(taxable_income)


def get_employee_tax_summary(employee_id: str, fy: str = CURRENT_FY) -> dict:
    """Get tax summary for an employee for a financial year."""
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
    """Get monthly TDS records, optionally filtered by month and FY."""
    df = read_csv(CSV_TDS)
    if month:
        df = df[df["month"] == str(month)]
    if fy:
        df = df[df["financial_year"] == fy]
    return df.to_dict(orient="records")


def get_tax_regime_comparison(employee_id: str, fy: str = CURRENT_FY) -> dict:
    """Compare tax liability under OLD vs NEW regime for an employee."""
    from services.payroll_service import get_employee_salary
    
    salary_data = get_employee_salary(employee_id)
    if not salary_data:
        return {"error": "Employee salary data not found"}
    
    basic = float(salary_data.get("basic_salary", 0))
    hra = float(salary_data.get("hra", 0))
    special = float(salary_data.get("special_allowance", 0))
    other = float(salary_data.get("other_allowances", 0))
    
    monthly_gross = basic + hra + special + other
    annual_gross = monthly_gross * 12
    
    # Get deductions from employee salary CSV
    regime = salary_data.get("tds_regime", "NEW")
    section_80c = float(salary_data.get("section_80C", 0))
    section_80d = float(salary_data.get("section_80D", 0))
    hra_exemption = float(salary_data.get("hra_exemption", 0))
    pf_contribution = basic * (PF_PERCENTAGE / 100.0) * 12  # Annual PF
    
    # Calculate for OLD regime
    old_deductions = {
        "section_80C": section_80c,
        "section_80D": section_80d,
        "hra_exemption": hra_exemption,
        "pf_contribution": pf_contribution
    }
    old_taxable = calculate_taxable_income(annual_gross, "OLD", old_deductions)
    old_tax = apply_old_regime_slabs(old_taxable)
    old_tax_with_cess = old_tax + apply_cess(old_tax)
    
    # Calculate for NEW regime
    new_deductions = {
        "section_80C": 0,
        "section_80D": 0,
        "hra_exemption": 0,
        "pf_contribution": 0
    }
    new_taxable = calculate_taxable_income(annual_gross, "NEW", new_deductions)
    new_tax = apply_new_regime_slabs(new_taxable)
    new_tax_with_cess = new_tax + apply_cess(new_tax)
    
    return {
        "employee_id": employee_id,
        "fy": fy,
        "annual_gross": f"{annual_gross:,.2f}",
        "old_regime": {
            "taxable_income": f"{old_taxable:,.2f}",
            "tax_before_cess": f"{old_tax:,.2f}",
            "cess": f"{apply_cess(old_tax):,.2f}",
            "total_tax": f"{old_tax_with_cess:,.2f}",
            "monthly_tds": f"{old_tax_with_cess/12:,.2f}"
        },
        "new_regime": {
            "taxable_income": f"{new_taxable:,.2f}",
            "tax_before_cess": f"{new_tax:,.2f}",
            "cess": f"{apply_cess(new_tax):,.2f}",
            "total_tax": f"{new_tax_with_cess:,.2f}",
            "monthly_tds": f"{new_tax_with_cess/12:,.2f}"
        },
        "recommended_regime": "OLD" if old_tax_with_cess < new_tax_with_cess else "NEW",
        "savings": f"{abs(old_tax_with_cess - new_tax_with_cess):,.2f}"
    }


def compute_tds_for_month(month: str, fy: str) -> dict:
    """
    Compute TDS for all active employees for a given month and FY.
    Stores results in CSV_TDS and returns a status summary.
    """
    from services.payroll_service import get_employee_salary
    
    emps_df = read_csv(CSV_EMPLOYEES)
    if emps_df.empty:
        return {"status": "error", "message": "No employees found."}
    
    tds_df = read_csv(CSV_TDS)
    computed = 0
    skipped = 0
    
    for _, emp in emps_df.iterrows():
        if emp.get("status") != "ACTIVE":
            continue
        
        emp_id = emp["employee_id"]
        
        # Check if already computed
        if not tds_df.empty and "employee_id" in tds_df.columns:
            mask = (tds_df["employee_id"] == emp_id) & (tds_df["month"] == str(month)) & (tds_df["financial_year"] == fy)
            if mask.any():
                skipped += 1
                continue
        
        salary_data = get_employee_salary(emp_id)
        if not salary_data:
            continue
        
        basic = float(salary_data.get("basic_salary", 0))
        hra = float(salary_data.get("hra", 0))
        special = float(salary_data.get("special_allowance", 0))
        other = float(salary_data.get("other_allowances", 0))
        regime = salary_data.get("tds_regime", "NEW")
        if not regime or regime.strip() == "":
            regime = "NEW"
        
        monthly_gross = basic + hra + special + other
        annual_gross = monthly_gross * 12
        
        employee_deductions = {
            "basic_salary": basic,
            "section_80C": float(salary_data.get("section_80C", 0)),
            "section_80D": float(salary_data.get("section_80D", 0)),
            "hra_exemption": float(salary_data.get("hra_exemption", 0))
        }
        
        # Calculate TDS
        monthly_tds = calculate_tds(monthly_gross, regime, employee_deductions)
        
        # Calculate taxable income for records
        pf_contribution = basic * (PF_PERCENTAGE / 100.0) * 12
        deductions = {
            "section_80C": employee_deductions.get("section_80C", 0),
            "section_80D": employee_deductions.get("section_80D", 0),
            "hra_exemption": employee_deductions.get("hra_exemption", 0),
            "pf_contribution": pf_contribution
        }
        taxable_income = calculate_taxable_income(annual_gross, regime, deductions)
        
        if regime.upper() == "OLD":
            annual_tax = apply_old_regime_slabs(taxable_income)
        else:
            annual_tax = apply_new_regime_slabs(taxable_income)
        annual_tax_with_cess = annual_tax + apply_cess(annual_tax)
        
        tds_row = {
            "tds_id": f"TDS-{str(uuid.uuid4())[:8].upper()}",
            "employee_id": emp_id,
            "financial_year": fy,
            "month": str(month),
            "tax_regime": regime.upper(),
            "annual_taxable_income": f"{taxable_income:.2f}",
            "estimated_annual_tax": f"{annual_tax_with_cess:.2f}",
            "annual_tds": f"{annual_tax_with_cess:.2f}",
            "monthly_tds": f"{monthly_tds:.2f}",
            "payroll_id": "",
            "calculated_at": datetime.now().isoformat()
        }
        append_row(CSV_TDS, tds_row)
        computed += 1
    
    return {
        "status": "success",
        "message": f"TDS computed for {computed} employees. Skipped {skipped} (already computed)."
    }


def get_hr_dashboard_metrics(fy: str) -> dict:
    """
    Get HR dashboard metrics for a financial year.
    Returns summary data for the HR dashboard view.
    """
    payroll_df = read_csv(CSV_PAYROLL)
    tds_df = read_csv(CSV_TDS)
    emps_df = read_csv(CSV_EMPLOYEES)
    
    active_employees = 0
    if not emps_df.empty and "status" in emps_df.columns:
        active_employees = len(emps_df[emps_df["status"] == "ACTIVE"])
    
    total_gross = 0
    total_pf = 0
    total_pt = 0
    total_tds = 0
    total_net = 0
    months_processed = 0
    
    if not payroll_df.empty and "financial_year" in payroll_df.columns:
        fy_payroll = payroll_df[payroll_df["financial_year"] == fy]
        if not fy_payroll.empty:
            total_gross = pd.to_numeric(fy_payroll.get("gross_salary", 0), errors="coerce").sum()
            total_pf = pd.to_numeric(fy_payroll.get("employee_pf", 0), errors="coerce").sum()
            total_pt = pd.to_numeric(fy_payroll.get("professional_tax", 0), errors="coerce").sum()
            if "tds" in fy_payroll.columns:
                total_tds = pd.to_numeric(fy_payroll["tds"], errors="coerce").sum()
            total_net = pd.to_numeric(fy_payroll.get("net_salary", 0), errors="coerce").sum()
            months_processed = fy_payroll["month"].nunique() if "month" in fy_payroll.columns else 0
    
    total_tds_deducted = 0
    if not tds_df.empty and "financial_year" in tds_df.columns:
        fy_tds = tds_df[tds_df["financial_year"] == fy]
        if not fy_tds.empty:
            total_tds_deducted = pd.to_numeric(fy_tds.get("monthly_tds", 0), errors="coerce").sum()
    
    return {
        "active_employees": active_employees,
        "total_gross": f"{total_gross:,.2f}",
        "total_pf": f"{total_pf:,.2f}",
        "total_pt": f"{total_pt:,.2f}",
        "total_tds": f"{total_tds:,.2f}",
        "total_net": f"{total_net:,.2f}",
        "total_tds_deducted": f"{total_tds_deducted:,.2f}",
        "months_processed": months_processed,
        "fy": fy
    }