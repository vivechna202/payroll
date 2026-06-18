"""
form16_service.py – Form 16 (Annual Tax Certificate) Generator.

Phase 8: Functional Form 16 generation, Part A/B datasets, and merged TXT downloads.
"""

import os
import uuid
import pandas as pd
from datetime import datetime
from config import (
    CSV_EMPLOYEES, CSV_PAYROLL, CSV_TDS, CSV_DECLARATIONS, CSV_DECLARATION_ITEMS,
    CSV_PROOFS, CSV_FORM16, FORM16_FOLDER, CURRENT_FY, STANDARD_DEDUCTION
)
from services.csv_service import read_csv, csv_to_records, append_row
from services.tax_service import calculate_tax

CSV_FORM16_HISTORY = os.path.join(os.path.dirname(CSV_FORM16), "form16_history.csv")

QUARTER_MONTHS = {
    "Q1": ["4", "5", "6"],
    "Q2": ["7", "8", "9"],
    "Q3": ["10", "11", "12"],
    "Q4": ["1", "2", "3"]
}

def get_eligible_employees(fy: str = CURRENT_FY) -> list[dict]:
    """Return employees who have processed payroll records in the selected financial year."""
    emp_df = read_csv(CSV_EMPLOYEES)
    pay_df = read_csv(CSV_PAYROLL)
    
    if emp_df.empty or pay_df.empty:
        return []
        
    # Get list of employee IDs with processed payroll in this FY
    fy_pay = pay_df[(pay_df["financial_year"] == fy) & (pay_df["payroll_status"] == "PROCESSED")]
    if fy_pay.empty:
        return []
        
    paid_emp_ids = set(fy_pay["employee_id"].unique())
    
    eligible = []
    for _, emp in emp_df.iterrows():
        emp_id = emp["employee_id"]
        if emp_id in paid_emp_ids and emp.get("status") == "ACTIVE":
            eligible.append({
                "employee_id": emp_id,
                "name": emp.get("name", "Unknown"),
                "pan": emp.get("pan", "N/A"),
                "department": emp.get("department", "N/A"),
                "designation": emp.get("designation", "N/A")
            })
            
    return eligible

def get_form16_history(fy: str = None, employee_id: str = None) -> list[dict]:
    """Retrieve history records from form16_history.csv."""
    if not os.path.exists(CSV_FORM16_HISTORY):
        # Initialize
        pd.DataFrame(columns=[
            "generation_id", "employee_id", "financial_year",
            "generated_by", "generated_at", "file_name"
        ]).to_csv(CSV_FORM16_HISTORY, index=False)
        return []
        
    history = csv_to_records(CSV_FORM16_HISTORY)
    if fy:
        history = [h for h in history if h.get("financial_year") == fy]
    if employee_id:
        history = [h for h in history if h.get("employee_id") == employee_id]
    return history

def generate_form16(employee_id: str, fy: str, generated_by: str) -> dict:
    """Generate Part A CSV, Part B CSV, and merged TXT Form 16 files for an employee."""
    os.makedirs(FORM16_FOLDER, exist_ok=True)
    
    # Read files
    emp_df = read_csv(CSV_EMPLOYEES)
    pay_df = read_csv(CSV_PAYROLL)
    tds_df = read_csv(CSV_TDS)
    decl_df = read_csv(CSV_DECLARATIONS)
    items_df = read_csv(CSV_DECLARATION_ITEMS)
    proof_df = read_csv(CSV_PROOFS)
    
    emp_row = emp_df[emp_df["employee_id"] == employee_id]
    if emp_row.empty:
        return {"status": "error", "message": f"Employee {employee_id} not found."}
    emp = emp_row.iloc[0].to_dict()
    
    # Get payroll for employee in FY
    emp_pay = pay_df[(pay_df["employee_id"] == employee_id) & (pay_df["financial_year"] == fy)]
    if emp_pay.empty:
        return {"status": "error", "message": f"No payroll records found for employee {employee_id} in FY {fy}."}
        
    # Get TDS for employee in FY
    emp_tds = pd.DataFrame()
    if not tds_df.empty:
        emp_tds = tds_df[(tds_df["employee_id"] == employee_id) & (tds_df["financial_year"] == fy)]
        
    # Get declaration and approved proofs
    regime = "NEW"
    approved_deductions = {}
    decl_id = None
    
    if not decl_df.empty:
        emp_decl = decl_df[(decl_df["employee_id"] == employee_id) & (decl_df["financial_year"] == fy) & (decl_df["status"] == "SUBMITTED")]
        if not emp_decl.empty:
            decl = emp_decl.iloc[-1].to_dict()
            regime = decl.get("tax_regime", "NEW").upper()
            decl_id = decl.get("declaration_id")
            
            # Find approved sections
            if decl_id and not items_df.empty:
                decl_items = items_df[items_df["declaration_id"] == decl_id]
                for _, item in decl_items.iterrows():
                    sec = item["section"]
                    amt = float(item["amount"])
                    
                    # Verify approved proof
                    if not proof_df.empty:
                        proofs = proof_df[(proof_df["declaration_id"] == decl_id) & (proof_df["section"] == sec) & (proof_df["status"] == "APPROVED")]
                        if not proofs.empty:
                            approved_deductions[sec] = amt

    # Calculate Salary components
    basic_sum = pd.to_numeric(emp_pay["basic_salary"], errors="coerce").sum()
    hra_sum = pd.to_numeric(emp_pay["hra"], errors="coerce").sum()
    special_sum = pd.to_numeric(emp_pay["special_allowance"], errors="coerce").sum()
    other_sum = pd.to_numeric(emp_pay["other_allowances"], errors="coerce").sum()
    gross_sum = pd.to_numeric(emp_pay["gross_salary"], errors="coerce").sum()
    pf_sum = pd.to_numeric(emp_pay["employee_pf"], errors="coerce").sum()
    pt_sum = pd.to_numeric(emp_pay["professional_tax"], errors="coerce").sum()
    
    tds_sum = 0.0
    if not emp_tds.empty:
        tds_sum = pd.to_numeric(emp_tds["monthly_tds"], errors="coerce").sum()

    # Part A: Quarter-wise salary and TDS deposit breakdown
    part_a_data = []
    for q, months in sorted(QUARTER_MONTHS.items()):
        q_pay = emp_pay[emp_pay["month"].isin(months)]
        q_tds = pd.DataFrame()
        if not emp_tds.empty:
            q_tds = emp_tds[emp_tds["month"].isin(months)]
            
        q_gross = pd.to_numeric(q_pay["gross_salary"], errors="coerce").sum()
        q_tds_dep = pd.to_numeric(q_tds["monthly_tds"], errors="coerce").sum() if not q_tds.empty else 0.0
        
        part_a_data.append({
            "quarter": q,
            "gross_salary": q_gross,
            "tds_deducted": q_tds_dep,
            "tds_deposited": q_tds_dep
        })
        
    # Save Part A Dataset CSV
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    part_a_filename = f"PartA_{employee_id}_{fy}_{timestamp}.csv"
    part_a_filepath = os.path.join(FORM16_FOLDER, part_a_filename)
    pd.DataFrame(part_a_data).to_csv(part_a_filepath, index=False)
    
    # Part B Calculations
    exemptions_10 = 0.0
    # In Old regime, check HRA exemption. We pull HRA from approved deductions if declared under OLD.
    if regime == "OLD":
        exemptions_10 = approved_deductions.get("HRA", 0.0)
        
    balance_salary = gross_sum - exemptions_10
    
    # Standard Deduction & PT
    std_ded = STANDARD_DEDUCTION
    pt_ded = pt_sum
    
    # Section 80 Deductions (for OLD regime)
    sec_80c = pf_sum  # PF is included in 80C
    if regime == "OLD":
        sec_80c += approved_deductions.get("80C", 0.0)
        # Limit 80C to 1.5L
        sec_80c = min(150000.0, sec_80c)
        
    other_80_deductions = 0.0
    if regime == "OLD":
        for sec, amt in approved_deductions.items():
            if sec not in ["HRA", "80C"]:
                other_80_deductions += amt
                
    total_deductions = std_ded + pt_ded + sec_80c + other_80_deductions if regime == "OLD" else std_ded + pt_ded
    
    taxable_income = max(0.0, balance_salary - total_deductions)
    
    # Calculate tax
    tax_base = calculate_tax(taxable_income, regime)
    cess = tax_base * 0.04
    total_tax_liability = tax_base + cess
    
    part_b_row = {
        "gross_salary": gross_sum,
        "basic_salary": basic_sum,
        "hra": hra_sum,
        "special_allowance": special_sum,
        "other_allowances": other_sum,
        "exemptions_us10": exemptions_10,
        "balance_salary": balance_salary,
        "standard_deduction": std_ded,
        "professional_tax": pt_ded,
        "section_80c": sec_80c,
        "other_80_deductions": other_80_deductions,
        "total_deductions": total_deductions,
        "taxable_income": taxable_income,
        "tax_on_income": tax_base,
        "cess_4_pct": cess,
        "total_tax_liability": total_tax_liability,
        "tds_credited": tds_sum,
        "refund_or_payable": total_tax_liability - tds_sum
    }
    
    # Save Part B Dataset CSV
    part_b_filename = f"PartB_{employee_id}_{fy}_{timestamp}.csv"
    part_b_filepath = os.path.join(FORM16_FOLDER, part_b_filename)
    pd.DataFrame([part_b_row]).to_csv(part_b_filepath, index=False)
    
    # 3. Create Merged Downloadable Form 16 Output (.txt)
    merged_filename = f"Form16_{employee_id}_{fy}_{timestamp}.txt"
    merged_filepath = os.path.join(FORM16_FOLDER, merged_filename)
    
    with open(merged_filepath, "w") as f:
        f.write("=" * 80 + "\n")
        f.write("FORM NO. 16 (PROTOTYPE ANNUAL TDS CERTIFICATE)\n")
        f.write(f"Certificate under section 203 of the Income-tax Act, 1961 for tax deducted at\n")
        f.write(f"source from income under the head 'Salaries'\n")
        f.write("=" * 80 + "\n\n")
        
        # Part A section
        f.write("PART A: CERTIFICATE OF TDS DEDUCTED AND DEPOSITED\n")
        f.write("-" * 80 + "\n")
        f.write(f"Employer Name: TAXPRO Pvt Ltd           | Employee Name: {emp['name']}\n")
        f.write(f"Employer Address: Tech Park, Mumbai     | Employee PAN: {emp['pan']}\n")
        f.write(f"Employer TAN: TAN-MOCK-HR001             | Employee ID: {employee_id}\n")
        f.write(f"Financial Year: {fy}                   | Assessment Year: 2025-26\n")
        f.write("-" * 80 + "\n")
        f.write(f"{'Quarter':<10} | {'Gross Salary Paid (INR)':<25} | {'TDS Deducted & Deposited (INR)':<30}\n")
        f.write("-" * 80 + "\n")
        for q_row in part_a_data:
            f.write(f"{q_row['quarter']:<10} | {q_row['gross_salary']:<25.2f} | {q_row['tds_deducted']:<30.2f}\n")
        f.write("-" * 80 + "\n")
        f.write(f"{'Total':<10} | {gross_sum:<25.2f} | {tds_sum:<30.2f}\n")
        f.write("=" * 80 + "\n\n")
        
        # Part B section
        f.write("PART B: COMPUTATION OF INCOME AND TAX LIABILITY\n")
        f.write("-" * 80 + "\n")
        f.write(f"1. Gross Salary (Total):                      INR {gross_sum:,.2f}\n")
        f.write(f"   - Basic Salary:                            INR {basic_sum:,.2f}\n")
        f.write(f"   - House Rent Allowance (HRA):              INR {hra_sum:,.2f}\n")
        f.write(f"   - Special Allowance:                       INR {special_sum:,.2f}\n")
        f.write(f"   - Other Allowances:                        INR {other_sum:,.2f}\n")
        f.write(f"2. Less: Allowance exempt u/s 10 (e.g. HRA):  INR {exemptions_10:,.2f}\n")
        f.write(f"3. Balance (Gross - Exemptions):              INR {balance_salary:,.2f}\n")
        f.write(f"4. Deductions under Chapter VI-A (Regime: {regime}):\n")
        f.write(f"   - Standard Deduction:                      INR {std_ded:,.2f}\n")
        f.write(f"   - Professional Tax u/s 16(iii):            INR {pt_ded:,.2f}\n")
        if regime == "OLD":
            f.write(f"   - Section 80C Deductions (incl. PF):       INR {sec_80c:,.2f}\n")
            f.write(f"   - Other Section 80 Deductions:             INR {other_80_deductions:,.2f}\n")
        f.write(f"5. Total Deductions allowed:                  INR {total_deductions:,.2f}\n")
        f.write(f"6. Net Taxable Income:                        INR {taxable_income:,.2f}\n")
        f.write("-" * 80 + "\n")
        f.write(f"7. Tax computed on Taxable Income:            INR {tax_base:,.2f}\n")
        f.write(f"8. Health & Education Cess @ 4%:              INR {cess:,.2f}\n")
        f.write(f"9. Total Tax Liability:                       INR {total_tax_liability:,.2f}\n")
        f.write(f"10. Total TDS Credited / Deposited:           INR {tds_sum:,.2f}\n")
        diff = total_tax_liability - tds_sum
        if diff > 0:
            f.write(f"11. Net Tax Payable (Outstanding):            INR {diff:,.2f}\n")
        else:
            f.write(f"11. Net Refund Due to Employee:               INR {abs(diff):,.2f}\n")
        f.write("=" * 80 + "\n")
        f.write(f"Generated By: {generated_by} | Date: {datetime.now().isoformat()}\n")
        f.write("End of Document\n")
        
    # 4. Save to history CSV
    # Ensure file exists first
    get_form16_history()
    
    generation_id = f"F16-{str(uuid.uuid4())[:8].upper()}"
    append_row(CSV_FORM16_HISTORY, {
        "generation_id": generation_id,
        "employee_id": employee_id,
        "financial_year": fy,
        "generated_by": generated_by,
        "generated_at": datetime.now().isoformat(),
        "file_name": merged_filename
    })
    
    return {
        "status": "success",
        "filename": merged_filename,
        "filepath": merged_filepath,
        "message": f"Form 16 generated successfully for {emp['name']}."
    }

def bulk_generate_form16(fy: str, generated_by: str) -> dict:
    """Generate Form 16 for all eligible employees for the financial year."""
    eligible = get_eligible_employees(fy)
    if not eligible:
        return {"status": "error", "message": f"No eligible employees found for FY {fy}."}
        
    success_count = 0
    fail_count = 0
    errors = []
    
    for emp in eligible:
        res = generate_form16(emp["employee_id"], fy, generated_by)
        if res["status"] == "success":
            success_count += 1
        else:
            fail_count += 1
            errors.append(f"Employee {emp['employee_id']}: {res['message']}")
            
    return {
        "status": "success",
        "message": f"Bulk generation complete. Success: {success_count}, Failed: {fail_count}.",
        "success_count": success_count,
        "fail_count": fail_count,
        "errors": errors
    }

def get_form16_details(employee_id: str, fy: str) -> dict:
    """Return computation details of Form 16 for display in UI (or empty values if payroll/TDS not processed)."""
    emp_df = read_csv(CSV_EMPLOYEES)
    pay_df = read_csv(CSV_PAYROLL)
    tds_df = read_csv(CSV_TDS)
    decl_df = read_csv(CSV_DECLARATIONS)
    items_df = read_csv(CSV_DECLARATION_ITEMS)
    proof_df = read_csv(CSV_PROOFS)
    
    emp_row = emp_df[emp_df["employee_id"] == employee_id]
    if emp_row.empty:
        return {}
    emp = emp_row.iloc[0].to_dict()
    
    emp_pay = pay_df[(pay_df["employee_id"] == employee_id) & (pay_df["financial_year"] == fy)]
    if emp_pay.empty:
        return {}
        
    emp_tds = pd.DataFrame()
    if not tds_df.empty:
        emp_tds = tds_df[(tds_df["employee_id"] == employee_id) & (tds_df["financial_year"] == fy)]
        
    regime = "NEW"
    approved_deductions = {}
    decl_id = None
    
    if not decl_df.empty:
        emp_decl = decl_df[(decl_df["employee_id"] == employee_id) & (decl_df["financial_year"] == fy) & (decl_df["status"] == "SUBMITTED")]
        if not emp_decl.empty:
            decl = emp_decl.iloc[-1].to_dict()
            regime = decl.get("tax_regime", "NEW").upper()
            decl_id = decl.get("declaration_id")
            
            if decl_id and not items_df.empty:
                decl_items = items_df[items_df["declaration_id"] == decl_id]
                for _, item in decl_items.iterrows():
                    sec = item["section"]
                    amt = float(item["amount"])
                    if not proof_df.empty:
                        proofs = proof_df[(proof_df["declaration_id"] == decl_id) & (proof_df["section"] == sec) & (proof_df["status"] == "APPROVED")]
                        if not proofs.empty:
                            approved_deductions[sec] = amt

    basic_sum = pd.to_numeric(emp_pay["basic_salary"], errors="coerce").sum()
    hra_sum = pd.to_numeric(emp_pay["hra"], errors="coerce").sum()
    special_sum = pd.to_numeric(emp_pay["special_allowance"], errors="coerce").sum()
    other_sum = pd.to_numeric(emp_pay["other_allowances"], errors="coerce").sum()
    gross_sum = pd.to_numeric(emp_pay["gross_salary"], errors="coerce").sum()
    pf_sum = pd.to_numeric(emp_pay["employee_pf"], errors="coerce").sum()
    pt_sum = pd.to_numeric(emp_pay["professional_tax"], errors="coerce").sum()
    
    tds_sum = 0.0
    if not emp_tds.empty:
        tds_sum = pd.to_numeric(emp_tds["monthly_tds"], errors="coerce").sum()
        
    exemptions_10 = approved_deductions.get("HRA", 0.0) if regime == "OLD" else 0.0
    balance_salary = gross_sum - exemptions_10
    std_ded = STANDARD_DEDUCTION
    pt_ded = pt_sum
    
    sec_80c = pf_sum
    if regime == "OLD":
        sec_80c += approved_deductions.get("80C", 0.0)
        sec_80c = min(150000.0, sec_80c)
        
    other_80_deductions = 0.0
    if regime == "OLD":
        for sec, amt in approved_deductions.items():
            if sec not in ["HRA", "80C"]:
                other_80_deductions += amt
                
    total_deductions = std_ded + pt_ded + sec_80c + other_80_deductions if regime == "OLD" else std_ded + pt_ded
    taxable_income = max(0.0, balance_salary - total_deductions)
    tax_base = calculate_tax(taxable_income, regime)
    cess = tax_base * 0.04
    total_tax_liability = tax_base + cess
    
    return {
        "employee_id": employee_id,
        "name": emp.get("name"),
        "pan": emp.get("pan"),
        "regime": regime,
        "employer_tan": "TAN-MOCK-HR001",
        "gross_salary": gross_sum,
        "basic_salary": basic_sum,
        "hra": hra_sum,
        "special_allowance": special_sum,
        "other_allowances": other_sum,
        "exemptions_us10": exemptions_10,
        "balance_salary": balance_salary,
        "standard_deduction": std_ded,
        "professional_tax": pt_ded,
        "section_80c": sec_80c,
        "other_80_deductions": other_80_deductions,
        "total_deductions": total_deductions,
        "taxable_income": taxable_income,
        "tax_on_income": tax_base,
        "cess_4_pct": cess,
        "total_tax_liability": total_tax_liability,
        "tds_credited": tds_sum,
        "refund_or_payable": total_tax_liability - tds_sum
    }

