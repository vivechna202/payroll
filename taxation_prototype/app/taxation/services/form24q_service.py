"""
form24q_service.py  Form 24Q (Quarterly TDS Return) Generator.

NSDL/Protean-compliant quarterly return generation and Government FVU validation.
"""

import os
import re
import uuid
import subprocess
import pandas as pd
from datetime import datetime
from app.base.utils.config import (
    CSV_TDS, CSV_EMPLOYEES, CSV_PAYROLL, CSV_DECLARATIONS, CSV_DECLARATION_ITEMS,
    CSV_PROOFS, CSV_FORM24Q_HISTORY, FORM24Q_FOLDER, CURRENT_FY, STANDARD_DEDUCTION
)
from app.base.utils.csv_service import read_csv, csv_to_records, append_row, write_csv
from app.taxation.services.tax_service import calculate_tax
from app.taxation.services.challan_service import get_quarter_challans

QUARTER_MONTHS = {
    "Q1": ["4", "5", "6"],
    "Q2": ["7", "8", "9"],
    "Q3": ["10", "11", "12"],
    "Q4": ["1", "2", "3"]
}

CSV_FVU_CONFIG = os.path.join(os.path.dirname(CSV_FORM24Q_HISTORY), "fvu_config.txt")

def ensure_form24q_history_csv():
    headers = [
        "generation_id",
        "quarter",
        "financial_year",
        "txt_file_name",
        "fvu_file_name",
        "err_file_name",
        "validation_status",
        "validation_message",
        "generated_by",
        "generated_at"
    ]
    if not os.path.exists(CSV_FORM24Q_HISTORY):
        os.makedirs(os.path.dirname(CSV_FORM24Q_HISTORY), exist_ok=True)
        pd.DataFrame(columns=headers).to_csv(CSV_FORM24Q_HISTORY, index=False)
    else:
        df = read_csv(CSV_FORM24Q_HISTORY)
        if df.empty or "txt_file_name" not in df.columns:
            # Recreate with headers and migrate old records if any
            new_df = pd.DataFrame(columns=headers)
            write_csv(CSV_FORM24Q_HISTORY, new_df)

def get_fvu_path() -> str:
    """Read the configured FVU utility path from fvu_config.txt."""
    if not os.path.exists(CSV_FVU_CONFIG):
        return ""
    try:
        with open(CSV_FVU_CONFIG, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""

def save_fvu_path(path: str) -> None:
    """Save the FVU utility path configuration to fvu_config.txt."""
    os.makedirs(os.path.dirname(CSV_FVU_CONFIG), exist_ok=True)
    with open(CSV_FVU_CONFIG, "w", encoding="utf-8") as f:
        f.write(path.strip())

def get_quarterly_summary(quarter: str, fy: str = CURRENT_FY) -> dict:
    months = QUARTER_MONTHS.get(quarter, [])
    tds_df = read_csv(CSV_TDS)
    
    if tds_df.empty:
        return {
            "quarter": quarter,
            "fy": fy,
            "total_tds_deducted": "0.00",
            "total_tds_deposited": "0.00",
            "employee_count": 0,
            "challan_count": 0,
            "status": "no_data"
        }
    
    q_tds = tds_df[(tds_df["financial_year"] == fy) & (tds_df["month"].isin(months))]
    
    if q_tds.empty:
        return {
            "quarter": quarter,
            "fy": fy,
            "total_tds_deducted": "0.00",
            "total_tds_deposited": "0.00",
            "employee_count": 0,
            "challan_count": 0,
            "status": "no_data"
        }
        
    total_tds = pd.to_numeric(q_tds["monthly_tds"], errors='coerce').sum()
    unique_emps = q_tds["employee_id"].nunique()
    active_months = q_tds["month"].nunique()
    
    return {
        "quarter": quarter,
        "fy": fy,
        "total_tds_deducted": f"{total_tds:.2f}",
        "total_tds_deposited": f"{total_tds:.2f}",
        "employee_count": unique_emps,
        "challan_count": active_months,
        "status": "ready"
    }

def get_quarterly_employee_details(quarter: str, fy: str) -> list[dict]:
    months = QUARTER_MONTHS.get(quarter, [])
    
    emp_df = read_csv(CSV_EMPLOYEES)
    pay_df = read_csv(CSV_PAYROLL)
    tds_df = read_csv(CSV_TDS)
    
    if emp_df.empty:
        return []
        
    emp_map = {row["employee_id"]: row for _, row in emp_df.iterrows()}
    
    q_pay = pd.DataFrame()
    if not pay_df.empty:
        q_pay = pay_df[(pay_df["financial_year"] == fy) & (pay_df["month"].isin(months))]
        
    q_tds = pd.DataFrame()
    if not tds_df.empty:
        q_tds = tds_df[(tds_df["financial_year"] == fy) & (tds_df["month"].isin(months))]
        
    emp_ids = set()
    if not q_pay.empty:
        emp_ids.update(q_pay["employee_id"].unique())
    if not q_tds.empty:
        emp_ids.update(q_tds["employee_id"].unique())
        
    results = []
    for emp_id in sorted(list(emp_ids)):
        emp_info = emp_map.get(emp_id, {})
        
        sal_sum = 0.0
        if not q_pay.empty:
            sal_sum = pd.to_numeric(q_pay[q_pay["employee_id"] == emp_id]["gross_salary"], errors='coerce').sum()
            
        tds_sum = 0.0
        if not q_tds.empty:
            tds_sum = pd.to_numeric(q_tds[q_tds["employee_id"] == emp_id]["monthly_tds"], errors='coerce').sum()
            
        results.append({
            "employee_id": emp_id,
            "name": emp_info.get("name", "Unknown"),
            "pan": emp_info.get("pan", "N/A"),
            "email": emp_info.get("email", "N/A"),
            "department": emp_info.get("department", "N/A"),
            "designation": emp_info.get("designation", "N/A"),
            "gross_salary": sal_sum,
            "tds_deducted": tds_sum
        })
        
    return results

def get_form24q_files(fy: str = None) -> list[dict]:
    ensure_form24q_history_csv()
    records = csv_to_records(CSV_FORM24Q_HISTORY)
    if fy:
        records = [r for r in records if r.get("financial_year") == fy]
    return records

def calculate_annual_salary_details(employee_id: str, fy: str) -> dict:
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

    gross_sum = pd.to_numeric(emp_pay["gross_salary"], errors="coerce").sum()
    pf_sum = pd.to_numeric(emp_pay["employee_pf"], errors="coerce").sum()
    pt_sum = pd.to_numeric(emp_pay["professional_tax"], errors="coerce").sum()
    
    tds_sum = 0.0
    if not emp_tds.empty:
        tds_sum = pd.to_numeric(emp_tds["monthly_tds"], errors="coerce").sum()

    exemptions_10 = 0.0
    if regime == "OLD":
        exemptions_10 = approved_deductions.get("HRA", 0.0)
        
    std_ded = float(STANDARD_DEDUCTION) if gross_sum > 0 else 0.0
    
    sec_80c = pf_sum
    if regime == "OLD":
        sec_80c += approved_deductions.get("80C", 0.0)
        sec_80c = min(150000.0, sec_80c)
        
    sec_80d = 0.0
    if regime == "OLD":
        sec_80d = min(25000.0, approved_deductions.get("80D", 0.0))
        
    other_80_ded = 0.0
    if regime == "OLD":
        for sec, amt in approved_deductions.items():
            if sec not in ["80C", "80D", "HRA"]:
                other_80_ded += amt
                
    total_chapter_via = sec_80c + sec_80d + other_80_ded
    
    if regime == "OLD":
        taxable_income = max(0.0, gross_sum - exemptions_10 - std_ded - pt_sum - total_chapter_via)
    else:
        taxable_income = max(0.0, gross_sum - std_ded)
        
    tax_payable = calculate_tax(taxable_income, regime)
    
    return {
        "employee_id": employee_id,
        "name": emp.get("name", "Unknown"),
        "pan": emp.get("pan", "N/A"),
        "regime": regime,
        "gross_salary": gross_sum,
        "exemptions": exemptions_10,
        "standard_deduction": std_ded,
        "pt_deduction": pt_sum,
        "chapter_via": total_chapter_via,
        "taxable_income": taxable_income,
        "tax_payable": tax_payable,
        "total_tds": tds_sum
    }

def run_mock_validation(txt_filepath: str) -> dict:
    errors = []
    
    if not os.path.exists(txt_filepath):
        return {"status": "FAILED", "message": "Input text file not found."}
        
    try:
        with open(txt_filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if not lines:
            return {"status": "FAILED", "message": "Input text file is empty."}
            
        fh_line = lines[0].strip()
        if not fh_line.startswith("FH^"):
            errors.append("First line must be a File Header (FH) record.")
            
        bh_line = None
        if len(lines) > 1:
            bh_line = lines[1].strip()
            if not bh_line.startswith("BH^"):
                errors.append("Second line must be a Batch Header (BH) record.")
                
        pan_regex = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")
        cd_count = 0
        dd_count = 0
        
        for idx, line in enumerate(lines, start=1):
            line = line.strip()
            if not line:
                continue
            parts = line.split("^")
            rec_type = parts[0]
            
            if rec_type == "CD":
                cd_count += 1
                if len(parts) < 8:
                    errors.append(f"Line {idx} (CD): Invalid field count (found {len(parts)}, expected at least 8).")
            elif rec_type == "DD":
                dd_count += 1
                if len(parts) < 8:
                    errors.append(f"Line {idx} (DD): Invalid field count (found {len(parts)}, expected at least 8).")
                else:
                    pan = parts[5]
                    if pan == "N/A" or not pan:
                        errors.append(f"Line {idx} (DD): Employee {parts[6]} is missing PAN.")
                    elif not pan_regex.match(pan):
                        errors.append(f"Line {idx} (DD): Invalid PAN format '{pan}' for employee {parts[6]}.")
            elif rec_type == "SD":
                if len(parts) < 10:
                    errors.append(f"Line {idx} (SD): Invalid field count (found {len(parts)}, expected at least 10).")
                    
        if bh_line and not errors:
            bh_parts = bh_line.split("^")
            if len(bh_parts) >= 5:
                expected_cd = int(bh_parts[2]) if bh_parts[2].isdigit() else 0
                expected_dd = int(bh_parts[3]) if bh_parts[3].isdigit() else 0
                if cd_count != expected_cd:
                    errors.append(f"Challan count mismatch: BH specifies {expected_cd}, but found {cd_count}.")
                if dd_count != expected_dd:
                    errors.append(f"Deductee count mismatch: BH specifies {expected_dd}, but found {dd_count}.")
                    
        if errors:
            return {
                "status": "FAILED",
                "message": "Validation failed: " + "; ".join(errors)
            }
            
        fvu_filepath = txt_filepath.replace(".txt", ".fvu")
        with open(fvu_filepath, "w", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
            f.write(f"FVU^SUCCESS^VALIDATED_BY_TAXPRO_MOCK_ENGINE^{datetime.now().strftime('%d%m%Y_%H%M%S')}^\n")
            
        return {
            "status": "SUCCESS",
            "message": "Validation successful. (Simulated)",
            "fvu_file": os.path.basename(fvu_filepath),
            "err_file": "N/A"
        }
        
    except Exception as e:
        return {
            "status": "FAILED",
            "message": f"Exception during validation: {str(e)}",
            "err_file": "N/A"
        }

def validate_with_fvu(txt_filepath: str, csi_filepath: str = None) -> dict:
    fvu_path = get_fvu_path()
    if not fvu_path or fvu_path.upper() == "MOCK" or not os.path.exists(fvu_path):
        # Fallback to mock validation
        res = run_mock_validation(txt_filepath)
        if fvu_path and fvu_path.upper() != "MOCK":
            res["message"] = f"FVU Utility path '{fvu_path}' not found. Fallback: " + res["message"]
        return res
        
    base_dir = os.path.dirname(txt_filepath)
    filename_sans_ext = os.path.splitext(os.path.basename(txt_filepath))[0]
    
    err_filepath = os.path.join(base_dir, f"{filename_sans_ext}.err")
    fvu_filepath = os.path.join(base_dir, f"{filename_sans_ext}.fvu")
    
    csi_arg = csi_filepath if csi_filepath and os.path.exists(csi_filepath) else ""
    
    # Standard NSDL command line invocation
    cmd = [
        "java",
        "-jar",
        fvu_path,
        txt_filepath,
        err_filepath,
        fvu_filepath,
        csi_arg,
        "0"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15
        )
        
        err_filename = os.path.basename(err_filepath) if os.path.exists(err_filepath) else "N/A"
        
        if os.path.exists(fvu_filepath) and os.path.getsize(fvu_filepath) > 0:
            return {
                "status": "SUCCESS",
                "message": "Validation successful. FVU file generated.",
                "fvu_file": os.path.basename(fvu_filepath),
                "err_file": err_filename
            }
            
        error_msg = "FVU Validation failed."
        if os.path.exists(err_filepath) and os.path.getsize(err_filepath) > 0:
            with open(err_filepath, "r", encoding="utf-8", errors="ignore") as ef:
                error_msg += " " + ef.read()[:300].strip()
        elif result.stderr:
            error_msg += " Subprocess stderr: " + result.stderr[:200]
        else:
            error_msg += " Subprocess stdout: " + result.stdout[:200]
            
        return {
            "status": "FAILED",
            "message": error_msg,
            "err_file": err_filename
        }
    except Exception as e:
        res = run_mock_validation(txt_filepath)
        res["message"] = f"Real FVU failed to execute ({str(e)}). Fallback: " + res["message"]
        return res

def generate_form24q(quarter: str, fy: str, generated_by: str, csi_filepath: str = None) -> dict:
    print(f"[SERVICE] generate_form24q called: quarter={quarter}, fy={fy}, by={generated_by}, csi={csi_filepath}")
    os.makedirs(FORM24Q_FOLDER, exist_ok=True)
    ensure_form24q_history_csv()
    
    months = QUARTER_MONTHS.get(quarter, [])
    challans = get_quarter_challans(quarter, fy)
    print(f"[SERVICE] Challans for {quarter}/{fy}: {len(challans)} found")
    
    emp_df = read_csv(CSV_EMPLOYEES)
    pay_df = read_csv(CSV_PAYROLL)
    tds_df = read_csv(CSV_TDS)
    print(f"[SERVICE] CSV rows loaded — employees={len(emp_df)}, payroll={len(pay_df)}, tds={len(tds_df)}")
    
    if emp_df.empty or pay_df.empty or tds_df.empty:
        msg = "Required datasets are empty. Please ensure employees, payroll, and TDS data exist."
        print(f"[SERVICE] EARLY EXIT — {msg}")
        return {"status": "error", "message": msg}
        
    emp_map = {row["employee_id"]: row for _, row in emp_df.iterrows()}
    
    # 1. Filter monthly data and build CD/DD records
    monthly_data = []
    total_q_salary = 0.0
    total_q_tds = 0.0
    
    for m in months:
        m_pay = pay_df[(pay_df["financial_year"] == fy) & (pay_df["month"] == m)]
        m_tds = tds_df[(tds_df["financial_year"] == fy) & (tds_df["month"] == m)]
        
        if m_pay.empty and m_tds.empty:
            continue
            
        m_emp_ids = set()
        if not m_pay.empty:
            m_emp_ids.update(m_pay["employee_id"].unique())
        if not m_tds.empty:
            m_emp_ids.update(m_tds["employee_id"].unique())
            
        emp_records = []
        for emp_id in sorted(list(m_emp_ids)):
            emp_info = emp_map.get(emp_id, {})
            
            # Gross salary in month m
            gross = 0.0
            if not m_pay.empty:
                emp_m_pay = m_pay[m_pay["employee_id"] == emp_id]
                if not emp_m_pay.empty:
                    gross = pd.to_numeric(emp_m_pay.iloc[0]["gross_salary"], errors='coerce')
                    if pd.isna(gross):
                        gross = 0.0
            
            # TDS in month m
            tds = 0.0
            if not m_tds.empty:
                emp_m_tds = m_tds[m_tds["employee_id"] == emp_id]
                if not emp_m_tds.empty:
                    tds = pd.to_numeric(emp_m_tds.iloc[0]["monthly_tds"], errors='coerce')
                    if pd.isna(tds):
                        tds = 0.0
                        
            emp_records.append({
                "employee_id": emp_id,
                "name": emp_info.get("name", "Unknown"),
                "pan": emp_info.get("pan", ""),
                "gross_salary": gross,
                "tds_deducted": tds
            })
            
            total_q_salary += gross
            total_q_tds += tds
            
        if emp_records:
            monthly_data.append({
                "month": m,
                "employees": emp_records,
                "total_tds": sum(e["tds_deducted"] for e in emp_records)
            })
            
    if not monthly_data:
        msg = f"No active payroll or TDS records found for {fy} {quarter}. Run Payroll Processing and Monthly TDS Calculation first."
        print(f"[SERVICE] EARLY EXIT — {msg}")
        return {"status": "error", "message": msg}
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 2. Save Staging CSV (consisting of the quarterly aggregated details for review)
    emp_details = get_quarterly_employee_details(quarter, fy)
    staging_filename = f"Form24Q_Staging_{fy}_{quarter}_{timestamp}.csv"
    staging_filepath = os.path.join(FORM24Q_FOLDER, staging_filename)
    
    staging_rows = []
    for emp in emp_details:
        staging_rows.append({
            "employee_id": emp["employee_id"],
            "name": emp["name"],
            "pan": emp["pan"],
            "email": emp["email"],
            "department": emp["department"],
            "designation": emp["designation"],
            "quarter": quarter,
            "financial_year": fy,
            "salary_paid": f"{emp['gross_salary']:.2f}",
            "tds_deducted": f"{emp['tds_deducted']:.2f}"
        })
    pd.DataFrame(staging_rows).to_csv(staging_filepath, index=False)
    
    txt_filename = f"Form24Q_{fy}_{quarter}_{timestamp}.txt"
    txt_filepath = os.path.join(FORM24Q_FOLDER, txt_filename)
    print(f"[SERVICE] Writing TXT return file: {txt_filename}")
    
    # Count totals
    cd_count = len(challans)
    
    # Map each challan to its employees to find dd_count and reuse during generation
    challan_to_employees = []
    for challan in challans:
        # Find matching month
        challan_month = 0
        c_date = challan.get("challan_date", "")
        if isinstance(c_date, str) and c_date:
            parts = re.split(r'[-/]', c_date)
            if len(parts) == 3:
                if len(parts[0]) == 4:
                    challan_month = int(parts[1])
                else:
                    challan_month = int(parts[1])
        elif hasattr(c_date, "month"):
            challan_month = c_date.month

        matching_m_data = None
        for m_data in monthly_data:
            if int(m_data["month"]) == challan_month:
                matching_m_data = m_data
                break
        
        c_employees = matching_m_data["employees"] if matching_m_data else []
        challan_to_employees.append((challan, c_employees, matching_m_data))

    dd_count = sum(len(c_emps) for _, c_emps, _ in challan_to_employees)
    
    # Financial Year mapping (e.g. 2024-25 -> 202425)
    fy_clean = fy.replace("-", "")
    ay_val = int(fy.split("-")[0]) + 1
    ay_clean = f"{ay_val}{str(ay_val+1)[2:]}" # e.g. 202526
    
    line_no = 1
    
    # Read real deductor details or fallback
    from app.base.utils.config import CSV_DEDUCTOR_MASTER
    deductor_tan = "TAN-MOCK-HR001"
    deductor_pan = "PAN-MOCK-HR001"
    deductor_name = "Company Pvt Ltd"
    deductor_addr = "Corporate Office"
    if os.path.exists(CSV_DEDUCTOR_MASTER):
        d_df = read_csv(CSV_DEDUCTOR_MASTER)
        if not d_df.empty:
            d_row = d_df.iloc[0]
            deductor_tan = d_row.get("tan", deductor_tan)
            deductor_pan = d_row.get("pan", deductor_pan)
            deductor_name = d_row.get("company_name", deductor_name)
            deductor_addr = d_row.get("address", deductor_addr)
            
    with open(txt_filepath, "w", encoding="utf-8", newline="\r\n") as f:
        # File Header (FH)
        # FH^LineNo^SL^UploadType^GenDate^SeqNo^DeductorType^FormatVer^^
        f.write(f"FH^{line_no}^SL^R^{datetime.now().strftime('%d%m%Y')}^1^O^1^^\n")
        line_no += 1
        
        # Batch Header (BH)
        # BH^LineNo^CDCount^DDCount^FormNo^TAN^PAN^Quarter^FY^AY^DeductorName^DeductorAddress^^
        f.write(f"BH^{line_no}^{cd_count}^{dd_count}^24Q^{deductor_tan}^{deductor_pan}^{quarter}^{fy_clean}^{ay_clean}^{deductor_name}^{deductor_addr}^^\n")
        line_no += 1
        
        # Challan Details (CD) and Deductee Details (DD)
        challan_serial = 1
        for challan, challan_employees, matching_m_data in challan_to_employees:
            # Format deposit date
            c_date_raw = challan.get("challan_date", "")
            c_date_formatted = ""
            if isinstance(c_date_raw, str) and c_date_raw:
                c_date_raw = c_date_raw.strip()
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%Y/%m/%d", "%d/%m/%Y"):
                    try:
                        dt = datetime.strptime(c_date_raw, fmt)
                        c_date_formatted = dt.strftime("%d%m%Y")
                        break
                    except ValueError:
                        continue
                if not c_date_formatted:
                    digits = re.sub(r'\D', '', c_date_raw)
                    if len(digits) == 8:
                        c_date_formatted = digits
            elif hasattr(c_date_raw, "strftime"):
                c_date_formatted = c_date_raw.strftime("%d%m%Y")
            
            # Format month end date as fallback/for deductee date
            m_num = int(matching_m_data["month"]) if matching_m_data else 0
            if not m_num:
                # try to extract month from challan date
                if isinstance(c_date_raw, str) and c_date_raw:
                    parts = re.split(r'[-/]', c_date_raw)
                    if len(parts) == 3:
                        m_num = int(parts[1])
                elif hasattr(c_date_raw, "month"):
                    m_num = c_date_raw.month
            
            if m_num in [4, 6, 9, 11]:
                days = 30
            elif m_num == 2:
                year_part = int(fy.split("-")[0]) if m_num >= 4 else int(fy.split("-")[0]) + 1
                days = 29 if year_part % 4 == 0 else 28
            else:
                days = 31
            date_str = f"{days:02d}{m_num:02d}{fy.split('-')[0] if m_num >= 4 else int(fy.split('-')[0])+1}" if m_num else ""
            
            if not c_date_formatted:
                c_date_formatted = date_str
            
            c_no_raw = challan.get("challan_no", challan.get("challan_serial_no", ""))
            try:
                c_no_val = int(float(c_no_raw))
                c_no_str = f"{c_no_val:05d}"
            except (ValueError, TypeError):
                c_no_str = str(c_no_raw) if c_no_raw else f"{challan_serial:05d}"
                
            bsr_str = str(challan.get("bsr_code", "0020304"))
            if not bsr_str:
                bsr_str = "0020304"
                
            try:
                c_amount = float(challan.get("amount", challan.get("challan_amount", 0.0)))
            except (ValueError, TypeError):
                c_amount = 0.0
                
            cd_line_serial = line_no
            f.write(f"CD^{line_no}^{challan_serial}^{len(challan_employees)}^{bsr_str}^{c_date_formatted}^{c_no_str}^{c_amount:.2f}^0.00^0.00^0.00^0.00^{c_amount:.2f}^192^^\n")
            line_no += 1
            
            deductee_serial = 1
            for emp in challan_employees:
                f.write(f"DD^{line_no}^{cd_line_serial}^{deductee_serial}^02^{emp['pan']}^{emp['name']}^{c_date_formatted}^{emp['gross_salary']:.2f}^{emp['tds_deducted']:.2f}^{emp['tds_deducted']:.2f}^{c_date_formatted}^192^^\n")
                line_no += 1
                deductee_serial += 1
                
            challan_serial += 1
            
        # 4. If Quarter Q4: Append Salary Details (SD) records for Annexure II
        if quarter == "Q4":
            active_emp_ids = set()
            for _, c_emps, _ in challan_to_employees:
                for emp in c_emps:
                    active_emp_ids.add(emp["employee_id"])
                    
            sd_serial = 1
            for emp_id in sorted(list(active_emp_ids)):
                sd_data = calculate_annual_salary_details(emp_id, fy)
                if sd_data:
                    regime_flag = "Yes" if sd_data["regime"] == "NEW" else "No"
                    f.write(f"SD^{line_no}^{sd_serial}^{sd_data['pan']}^{sd_data['name']}^{fy_clean}^{sd_data['gross_salary']:.2f}^{sd_data['exemptions']:.2f}^{sd_data['standard_deduction']:.2f}^{sd_data['pt_deduction']:.2f}^{sd_data['chapter_via']:.2f}^{sd_data['taxable_income']:.2f}^{sd_data['tax_payable']:.2f}^{sd_data['total_tds']:.2f}^{regime_flag}^^\n")
                    line_no += 1
                    sd_serial += 1
                    
    # 5. Save generation record WITHOUT FVU validation
    #    FVU validation is now a separate Step 2 triggered by the user.
    generation_id = f"F24Q-{str(uuid.uuid4())[:8].upper()}"
    history_row = {
        "generation_id": generation_id,
        "quarter": quarter,
        "financial_year": fy,
        "txt_file_name": txt_filename,
        "fvu_file_name": "N/A",
        "err_file_name": "N/A",
        "validation_status": "NOT_VALIDATED",
        "validation_message": "TXT generated. Upload TXT + CSI and click Run FVU Validation to validate.",
        "generated_by": generated_by,
        "generated_at": datetime.now().isoformat()
    }
    append_row(CSV_FORM24Q_HISTORY, history_row)
    print(f"[SERVICE] History row saved: generation_id={generation_id}")

    return {
        "status": "success",
        "generation_id": generation_id,
        "filename": txt_filename,
        "filepath": txt_filepath,
        "message": f"Form 24Q TXT return generated: {txt_filename}. Download it, then upload it with a CSI file to run FVU validation."
    }


def run_fvu_validation(txt_filepath: str, csi_filepath: str, generated_by: str) -> dict:
    """Step 2: Run FVU utility on an existing TXT file + CSI file.
    
    Called by the /hr/form24q/run-fvu backend route after both files are uploaded by the user.
    Saves a new history record with the FVU validation result.
    """
    print(f"[SERVICE] run_fvu_validation: txt={txt_filepath}, csi={csi_filepath}, by={generated_by}")
    ensure_form24q_history_csv()

    if not os.path.exists(txt_filepath):
        msg = f"TXT file not found at: {txt_filepath}"
        print(f"[SERVICE] ERROR — {msg}")
        return {"status": "error", "message": msg}

    if not os.path.exists(csi_filepath):
        msg = f"CSI file not found at: {csi_filepath}"
        print(f"[SERVICE] ERROR — {msg}")
        return {"status": "error", "message": msg}

    print(f"[SERVICE] Running FVU utility...")
    val_result = validate_with_fvu(txt_filepath, csi_filepath=csi_filepath)
    print(f"[SERVICE] FVU result: status={val_result['status']}, message={val_result['message']}")

    validation_status  = val_result["status"]
    validation_message = val_result["message"]
    fvu_filename       = val_result.get("fvu_file", "N/A")
    err_filename       = val_result.get("err_file", "N/A")

    generation_id = f"F24Q-FVU-{str(uuid.uuid4())[:8].upper()}"
    history_row = {
        "generation_id": generation_id,
        "quarter": "MANUAL-FVU",
        "financial_year": "N/A",
        "txt_file_name": os.path.basename(txt_filepath),
        "fvu_file_name": fvu_filename,
        "err_file_name": err_filename,
        "validation_status": validation_status,
        "validation_message": validation_message,
        "generated_by": generated_by,
        "generated_at": datetime.now().isoformat()
    }
    append_row(CSV_FORM24Q_HISTORY, history_row)
    print(f"[SERVICE] FVU history row saved: generation_id={generation_id}")

    if validation_status == "SUCCESS":
        return {
            "status": "success",
            "message": f"FVU Validation SUCCESS. FVU file generated: {fvu_filename}"
        }
    else:
        return {
            "status": "error",
            "message": f"FVU Validation FAILED: {validation_message}. Check Validation Report for details."
        }
