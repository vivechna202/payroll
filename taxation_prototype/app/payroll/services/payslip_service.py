import os
import uuid
import io
from datetime import datetime
import pandas as pd

from app.base.utils.config import (
    CSV_PAYSLIPS, CSV_PAYROLL, CSV_EMPLOYEES, CSV_DEDUCTOR_MASTER, 
    CURRENT_FY
)
from app.base.utils.csv_service import (
    read_csv, write_csv, append_row, read_csv_filtered
)

# For PDF Generation
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

def _generate_payslip_id(year: int, month: int) -> str:
    """Generates structured ID like PS-YYYY-MM-XXXX"""
    df = read_csv(CSV_PAYSLIPS)
    prefix = f"PS-{year}-{month:02d}-"
    
    if df.empty or "payslip_id" not in df.columns:
        return f"{prefix}0001"
    
    # Filter for this month
    mask = df["payslip_id"].str.startswith(prefix, na=False)
    if not mask.any():
        return f"{prefix}0001"
    
    max_id = df.loc[mask, "payslip_id"].max()
    try:
        num = int(max_id.split("-")[-1])
        return f"{prefix}{(num + 1):04d}"
    except (ValueError, IndexError):
        return f"{prefix}0001"

def generate_batch_payslips(batch_id: str, user: str) -> dict:
    payroll_df = read_csv_filtered(CSV_PAYROLL, "batch_id", batch_id)
    if payroll_df.empty:
        return {"status": "error", "message": "No payroll records found for this batch."}
    
    payslip_df = read_csv(CSV_PAYSLIPS)
    existing_payroll_ids = set()
    if not payslip_df.empty and "payroll_id" in payslip_df.columns:
        existing_payroll_ids = set(payslip_df["payroll_id"].dropna().tolist())
        
    created_count = 0
    _now = datetime.now().isoformat()
    
    for _, row in payroll_df.iterrows():
        payroll_id = row.get("payroll_id")
        
        if payroll_id in existing_payroll_ids:
            continue
            
        emp_id = row.get("employee_id")
        fy = row.get("financial_year")
        month = int(row.get("month", 0))
        
        # Need year to generate ID (assumes FY 2024-25, April is 2024, Jan is 2025)
        # Simplified assumption for year mapping:
        year = int(fy.split("-")[0]) if month >= 4 else int(fy.split("-")[0]) + 1
        
        ps_id = _generate_payslip_id(year, month)
        
        new_ps = {
            "payslip_id": ps_id,
            "payroll_id": payroll_id,
            "employee_id": emp_id,
            "financial_year": fy,
            "month": str(month),
            "status": "Draft",
            "remarks": "",
            "created_by": user,
            "created_at": _now,
            "confirmed_by": "",
            "confirmed_at": "",
            "paid_by": "",
            "paid_at": ""
        }
        append_row(CSV_PAYSLIPS, new_ps)
        existing_payroll_ids.add(payroll_id)
        created_count += 1
        
    return {"status": "success", "message": f"Generated {created_count} new payslips.", "count": created_count}

def generate_individual_payslip(payroll_id: str, user: str) -> dict:
    payslip_df = read_csv_filtered(CSV_PAYSLIPS, "payroll_id", payroll_id)
    if not payslip_df.empty:
        return {"status": "error", "message": "Payslip already exists for this payroll record."}
        
    payroll_df = read_csv_filtered(CSV_PAYROLL, "payroll_id", payroll_id)
    if payroll_df.empty:
        return {"status": "error", "message": "Payroll record not found."}
        
    row = payroll_df.iloc[0]
    emp_id = row.get("employee_id")
    fy = row.get("financial_year")
    month = int(row.get("month", 0))
    year = int(fy.split("-")[0]) if month >= 4 else int(fy.split("-")[0]) + 1
    
    ps_id = _generate_payslip_id(year, month)
    _now = datetime.now().isoformat()
    
    new_ps = {
        "payslip_id": ps_id,
        "payroll_id": payroll_id,
        "employee_id": emp_id,
        "financial_year": fy,
        "month": str(month),
        "status": "Draft",
        "remarks": "",
        "created_by": user,
        "created_at": _now,
        "confirmed_by": "",
        "confirmed_at": "",
        "paid_by": "",
        "paid_at": ""
    }
    append_row(CSV_PAYSLIPS, new_ps)
    return {"status": "success", "message": "Payslip generated.", "payslip_id": ps_id}

def _calculate_ytd(employee_id: str, current_fy: str) -> dict:
    """Calculates YTD totals from all PROCESSED payroll records for the FY"""
    df = read_csv(CSV_PAYROLL)
    if df.empty:
        return {}
        
    mask = (df["employee_id"] == employee_id) & (df["financial_year"] == current_fy) & (df["payroll_status"] == "PROCESSED")
    emp_df = df[mask]
    
    if emp_df.empty:
        return {}
        
    cols_to_sum = [
        "basic_salary", "hra", "special_allowance", "other_allowances", "gross_salary",
        "employee_pf", "professional_tax", "tds", "net_salary",
        "pf_employee", "pf_employer", "esi_employee", "esi_employer", "pt", "lwf",
        "bonus", "incentives", "overtime_amount", "lop_amount"
    ]
    
    ytd = {}
    for col in cols_to_sum:
        if col in emp_df.columns:
            ytd[col] = pd.to_numeric(emp_df[col], errors='coerce').fillna(0).sum()
        else:
            ytd[col] = 0.0
            
    return ytd

def get_payslip_details(payslip_id: str, request_user_id: str, request_role: str) -> dict | None:
    ps_df = read_csv_filtered(CSV_PAYSLIPS, "payslip_id", payslip_id)
    if ps_df.empty:
        return None
    ps_row = ps_df.iloc[0].to_dict()
    
    if request_role == "employee" and ps_row.get("employee_id") != request_user_id:
        return None # Unauthorized
        
    emp_id = ps_row.get("employee_id")
    payroll_id = ps_row.get("payroll_id")
    
    pay_df = read_csv_filtered(CSV_PAYROLL, "payroll_id", payroll_id)
    pay_row = pay_df.iloc[0].to_dict() if not pay_df.empty else {}
    
    emp_df = read_csv_filtered(CSV_EMPLOYEES, "employee_id", emp_id)
    emp_row = emp_df.iloc[0].to_dict() if not emp_df.empty else {}
    
    ded_df = read_csv(CSV_DEDUCTOR_MASTER)
    comp_row = ded_df.iloc[0].to_dict() if not ded_df.empty else {}
    
    ytd = _calculate_ytd(emp_id, ps_row.get("financial_year", CURRENT_FY))
    
    import json
    earnings_json = pay_row.get("earnings_json", "{}")
    deductions_json = pay_row.get("deductions_json", "{}")
    
    try:
        earnings_breakdown = json.loads(earnings_json) if pd.notna(earnings_json) else {}
    except:
        earnings_breakdown = {}
        
    try:
        deductions_breakdown = json.loads(deductions_json) if pd.notna(deductions_json) else {}
    except:
        deductions_breakdown = {}
    
    # Safe float parsing
    def sf(val):
        try: return float(val) if pd.notna(val) else 0.0
        except: return 0.0

    return {
        "payslip": ps_row,
        "payroll": pay_row,
        "employee": emp_row,
        "company": comp_row,
        "ytd": ytd,
        "breakdown": {
            "earnings": earnings_breakdown,
            "deductions": deductions_breakdown
        },
        "totals": {
            "basic": sf(pay_row.get("basic_salary")),
            "hra": sf(pay_row.get("hra")),
            "special": sf(pay_row.get("special_allowance")),
            "other": sf(pay_row.get("other_allowances")),
            "gross": sf(pay_row.get("gross_salary")),
            "pf": sf(pay_row.get("pf_employee", pay_row.get("employee_pf"))),
            "esi": sf(pay_row.get("esi_employee")),
            "pt": sf(pay_row.get("pt", pay_row.get("professional_tax"))),
            "lwf": sf(pay_row.get("lwf")),
            "tds": sf(pay_row.get("tds")),
            "net": sf(pay_row.get("net_salary")),
            "employer_pf": sf(pay_row.get("pf_employer")),
            "employer_esi": sf(pay_row.get("esi_employer"))
        }
    }

def get_payslips_by_batch(batch_id: str) -> list[dict]:
    # Need to join payroll.csv and payslips.csv
    pay_df = read_csv_filtered(CSV_PAYROLL, "batch_id", batch_id)
    if pay_df.empty or "payroll_id" not in pay_df.columns:
        return []
        
    ps_df = read_csv(CSV_PAYSLIPS)
    if ps_df.empty:
        return []
        
    merged = pd.merge(pay_df, ps_df, on="employee_id", how="inner")
    
    emp_df = read_csv(CSV_EMPLOYEES)
    if not emp_df.empty:
        merged = pd.merge(
        merged.reset_index() if "employee_id" not in merged.columns else merged,
        emp_df[["employee_id", "name"]],
        on="employee_id",
        how="left"
    ) 
        
    return merged.to_dict(orient="records")

def get_employee_payslips(employee_id: str) -> list[dict]:
    df = read_csv_filtered(CSV_PAYSLIPS, "employee_id", employee_id)
    if df.empty:
        return []
    # Filter confirmed and paid
    df = df[df["status"].isin(["Confirmed", "Paid"])]
    
    # Join with payroll to get net_salary
    pay_df = read_csv(CSV_PAYROLL)
    if not pay_df.empty and "payroll_id" in df.columns:
        merged = pd.merge(df, pay_df[["payroll_id", "net_salary"]], on="payroll_id", how="left")
        return merged.to_dict(orient="records")
    
    return df.to_dict(orient="records")

def update_payslip_status(payslip_id: str, status: str, user: str) -> dict:
    df = read_csv(CSV_PAYSLIPS)
    if df.empty or "payslip_id" not in df.columns:
        return {"status": "error", "message": "Payslip not found."}
        
    mask = df["payslip_id"] == payslip_id
    if not mask.any():
        return {"status": "error", "message": "Payslip not found."}
        
    idx = df.index[mask][0]
    current_status = df.at[idx, "status"]
    
    if current_status in ["Confirmed", "Paid"] and status in ["Draft", "Cancelled"]:
        return {"status": "error", "message": "Cannot modify a Confirmed or Paid payslip."}
        
    _now = datetime.now().isoformat()
    df.at[idx, "status"] = status
    if status == "Confirmed":
        df.at[idx, "confirmed_by"] = user
        df.at[idx, "confirmed_at"] = _now
    elif status == "Paid":
        df.at[idx, "paid_by"] = user
        df.at[idx, "paid_at"] = _now
        
    write_csv(CSV_PAYSLIPS, df)
    return {"status": "success", "message": f"Payslip marked as {status}."}

def regenerate_draft_payslip(payslip_id: str, user: str) -> dict:
    # Payslips don't have dynamic data to recalculate since they just pull from payroll.csv on the fly.
    # Regenerating essentially just clears remarks and sets to draft if it was cancelled.
    return update_payslip_status(payslip_id, "Draft", user)

def cancel_draft_payslip(payslip_id: str, user: str) -> dict:
    return update_payslip_status(payslip_id, "Cancelled", user)

def get_dashboard_stats(fy: str) -> dict:
    df = read_csv(CSV_PAYSLIPS)
    if df.empty:
        return {"total": 0, "draft": 0, "confirmed": 0, "paid": 0, "cancelled": 0, "amount": 0}
        
    df_fy = df[df["financial_year"] == fy]
    stats = {
        "total": len(df_fy),
        "draft": len(df_fy[df_fy["status"] == "Draft"]),
        "confirmed": len(df_fy[df_fy["status"] == "Confirmed"]),
        "paid": len(df_fy[df_fy["status"] == "Paid"]),
        "cancelled": len(df_fy[df_fy["status"] == "Cancelled"]),
        "amount": 0
    }
    
    # Calculate amount from confirmed/paid slips by joining with payroll.csv
    valid_ps = df_fy[df_fy["status"].isin(["Confirmed", "Paid"])]
    if not valid_ps.empty:
        pay_df = read_csv(CSV_PAYROLL)
        if not pay_df.empty:
            merged = pd.merge(valid_ps, pay_df, on="payroll_id", how="inner")
            if "net_salary" in merged.columns:
                stats["amount"] = pd.to_numeric(merged["net_salary"], errors='coerce').fillna(0).sum()
                
    return stats

def generate_payslip_pdf(payslip_details: dict) -> bytes:
    """Generates PDF natively using ReportLab"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elements = []
    styles = getSampleStyleSheet()
    
    # Extract data
    comp = payslip_details.get("company", {})
    emp = payslip_details.get("employee", {})
    ps = payslip_details.get("payslip", {})
    pay = payslip_details.get("payroll", {})
    totals = payslip_details.get("totals", {})
    ytd = payslip_details.get("ytd", {})
    
    # Header
    elements.append(Paragraph(f"<b>{comp.get('company_name', 'Company Name')}</b>", styles['Heading1']))
    elements.append(Paragraph(f"{comp.get('address', 'Address')}, {comp.get('state', '')}", styles['Normal']))
    elements.append(Spacer(1, 0.2*inch))
    
    elements.append(Paragraph(f"<b>Payslip for {ps.get('month', '')}/{ps.get('financial_year', '')}</b>", styles['Heading3']))
    elements.append(Spacer(1, 0.3*inch))
    
    # Employee Details
    data_emp = [
        ["Employee ID:", emp.get("employee_id", ""), "Name:", emp.get("name", "")],
        ["Designation:", emp.get("designation", ""), "Department:", emp.get("department", "")],
        ["PAN:", emp.get("pan", ""), "UAN:", emp.get("uan", "")],
        ["Payslip ID:", ps.get("payslip_id", ""), "Status:", ps.get("status", "")]
    ]
    t_emp = Table(data_emp, colWidths=[1.3*inch, 2.3*inch, 1.3*inch, 2.3*inch])
    t_emp.setStyle(TableStyle([
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('TOPPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(t_emp)
    elements.append(Spacer(1, 0.5*inch))
    
    # Salary Data
    data_sal = [
        ["Earnings", "Amount", "YTD", "Deductions", "Amount", "YTD"]
    ]
    
    def fv(val): return f"Rs. {val:,.2f}" if val else "Rs. 0.00"
    
    data_sal.append([
        "Basic Salary", fv(totals.get("basic")), fv(ytd.get("basic_salary")),
        "Provident Fund (PF)", fv(totals.get("pf")), fv(ytd.get("employee_pf"))
    ])
    data_sal.append([
        "House Rent Allowance", fv(totals.get("hra")), fv(ytd.get("hra")),
        "Professional Tax", fv(totals.get("pt")), fv(ytd.get("professional_tax"))
    ])
    data_sal.append([
        "Special Allowance", fv(totals.get("special")), fv(ytd.get("special_allowance")),
        "TDS", fv(totals.get("tds")), fv(ytd.get("tds"))
    ])
    
    t_sal = Table(data_sal, colWidths=[1.6*inch, 1.1*inch, 1.1*inch, 1.6*inch, 1.1*inch, 1.1*inch])
    t_sal.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#e2e8f0')),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#e2e8f0')),
        ('PADDING', (0,0), (-1,-1), 10),
        ('ALIGN', (1,0), (2,-1), 'RIGHT'),
        ('ALIGN', (4,0), (5,-1), 'RIGHT'),
    ]))
    elements.append(t_sal)
    elements.append(Spacer(1, 0.6*inch))
    
    # Summary Section (right-aligned, two-column)
    data_summary = [
        ["", "Gross Salary", fv(totals.get('gross'))],
        ["", "Total Deductions", fv(totals.get('gross') - totals.get('net'))],
        ["", "Net Salary", fv(totals.get('net'))]
    ]
    t_summary = Table(data_summary, colWidths=[3.5*inch, 2.2*inch, 2.2*inch])
    t_summary.setStyle(TableStyle([
        ('FONTNAME', (1,0), (1,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
        ('ALIGN', (2,0), (2,-1), 'RIGHT'),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
        ('LINEBELOW', (1,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
    ]))
    elements.append(t_summary)
    elements.append(Spacer(1, 2.8*inch))
    
    # Signatures
    data_sig = [
        ["________________________", "________________________", "________________________"],
        ["Employee Signature", "HR Signature", "Authorized Signatory"]
    ]
    t_sig = Table(data_sig, colWidths=[2.5*inch, 2.5*inch, 2.5*inch])
    t_sig.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('TOPPADDING', (0,0), (-1,-1), 10),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(t_sig)
    
    # Render PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer.read()
