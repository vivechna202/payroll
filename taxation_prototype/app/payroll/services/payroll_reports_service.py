"""
payroll_reports_service.py – Read-only analytics and reporting service.

Aggregates data from payroll.csv, employees.csv, contracts.csv,
payslips.csv, fnf_settlements.csv without modifying any records.
"""

import io
import pandas as pd
from datetime import datetime

from app.base.utils.config import (
    CSV_PAYROLL, CSV_EMPLOYEES, CSV_CONTRACTS, CSV_PAYROLL_BATCHES,
    CSV_PAYSLIPS, CSV_FNF, CSV_EMPLOYEE_SALARY
)
from app.base.utils.csv_service import read_csv


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _num(val, default=0.0):
    """Safely convert to float."""
    try:
        return float(val) if val and str(val).strip() != "" else default
    except (TypeError, ValueError):
        return default


def _load_processed_payroll(filters: dict = None) -> pd.DataFrame:
    """Load PROCESSED or LOCKED payroll rows, applying filters."""
    df = read_csv(CSV_PAYROLL)
    if df.empty:
        return pd.DataFrame()

    valid = ["PROCESSED", "LOCKED"]
    if "payroll_status" in df.columns:
        df = df[df["payroll_status"].isin(valid)]
    else:
        return pd.DataFrame()

    if filters:
        if filters.get("fy"):
            df = df[df["financial_year"] == filters["fy"]]
        if filters.get("month"):
            df = df[df["month"] == str(filters["month"])]
        if filters.get("batch_id"):
            df = df[df["batch_id"] == filters["batch_id"]]
        if filters.get("employee_id"):
            df = df[df["employee_id"].str.contains(filters["employee_id"], case=False, na=False)]

    # Join employees for name/department/designation
    emp_df = read_csv(CSV_EMPLOYEES)
    if not emp_df.empty:
        keep = [c for c in ["employee_id", "name", "department", "designation"] if c in emp_df.columns]
        df = pd.merge(df, emp_df[keep], on="employee_id", how="left")

    if filters and filters.get("department") and "department" in df.columns:
        df = df[df["department"] == filters["department"]]

    # Numeric cast for key columns
    for col in ["gross_salary", "net_salary", "basic_salary", "employee_pf",
                "professional_tax", "tds", "employer_cost", "pf_employer",
                "esi_employee", "esi_employer", "lwf", "bonus",
                "overtime_amount", "lop_amount"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        else:
            df[col] = 0.0

    return df.fillna("")


# ─────────────────────────────────────────────────────────────
# Dashboard Analytics
# ─────────────────────────────────────────────────────────────

def get_dashboard_analytics(filters: dict = None) -> dict:
    """Top-level KPIs for the reports dashboard."""
    df = _load_processed_payroll(filters)

    emp_df = read_csv(CSV_EMPLOYEES)
    total_employees = len(emp_df) if not emp_df.empty else 0

    contracts_df = read_csv(CSV_CONTRACTS)
    active_contracts = 0
    if not contracts_df.empty and "status" in contracts_df.columns:
        active_contracts = len(contracts_df[contracts_df["status"] == "active"])

    if df.empty:
        return {
            "total_employees": total_employees,
            "active_contracts": active_contracts,
            "total_gross": 0, "total_net": 0, "total_tds": 0,
            "total_pf": 0, "total_esi": 0, "employer_cost": 0,
            "avg_salary": 0, "max_salary": 0, "min_salary": 0,
            "record_count": 0,
        }

    return {
        "total_employees": total_employees,
        "active_contracts": active_contracts,
        "total_gross": round(df["gross_salary"].sum(), 2),
        "total_net": round(df["net_salary"].sum(), 2),
        "total_tds": round(df["tds"].sum(), 2),
        "total_pf": round(df["employee_pf"].sum(), 2),
        "total_esi": round(df["esi_employee"].sum(), 2),
        "employer_cost": round(df["employer_cost"].sum(), 2),
        "avg_salary": round(df["gross_salary"].mean(), 2),
        "max_salary": round(df["gross_salary"].max(), 2),
        "min_salary": round(df[df["gross_salary"] > 0]["gross_salary"].min(), 2) if (df["gross_salary"] > 0).any() else 0,
        "record_count": len(df),
    }


# ─────────────────────────────────────────────────────────────
# Chart Data
# ─────────────────────────────────────────────────────────────

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

def get_chart_data(filters: dict = None) -> dict:
    """Return serialisable chart data for Chart.js."""
    # Use all processed records for the chosen FY (ignore month filter for trends)
    trend_filters = {k: v for k, v in (filters or {}).items() if k != "month"}
    df = _load_processed_payroll(trend_filters)

    # 1. Monthly Payroll Trend
    monthly_trend = {"labels": [], "gross": [], "net": []}
    if not df.empty and "month" in df.columns:
        grouped = df.groupby("month").agg(
            gross=("gross_salary", "sum"), net=("net_salary", "sum")
        ).reset_index()
        grouped["month"] = pd.to_numeric(grouped["month"], errors="coerce").fillna(0).astype(int)
        grouped = grouped.sort_values("month")
        monthly_trend["labels"] = [MONTH_NAMES[m - 1] if 1 <= m <= 12 else str(m) for m in grouped["month"]]
        monthly_trend["gross"] = [round(v, 2) for v in grouped["gross"]]
        monthly_trend["net"] = [round(v, 2) for v in grouped["net"]]

    # 2. Department-wise Cost
    dept_cost = {"labels": [], "values": []}
    if not df.empty and "department" in df.columns:
        grouped = df.groupby("department")["gross_salary"].sum().sort_values(ascending=False)
        dept_cost["labels"] = list(grouped.index)
        dept_cost["values"] = [round(v, 2) for v in grouped.values]

    # 3. Statutory Breakdown (total across filtered period)
    statutory = {
        "labels": ["Employee PF", "Employer PF", "Employee ESI", "Employer ESI", "PT", "TDS"],
        "values": [
            round(df["employee_pf"].sum(), 2),
            round(df["pf_employer"].sum(), 2),
            round(df["esi_employee"].sum(), 2),
            round(df["esi_employer"].sum(), 2),
            round(df["professional_tax"].sum(), 2),
            round(df["tds"].sum(), 2),
        ]
    }

    # 4. Salary Distribution buckets
    sal_dist = {"labels": [], "values": []}
    if not df.empty:
        buckets = [0, 20000, 40000, 60000, 80000, 100000, float("inf")]
        bucket_labels = ["<20k", "20-40k", "40-60k", "60-80k", "80-100k", ">100k"]
        counts = []
        for i in range(len(buckets) - 1):
            count = len(df[(df["gross_salary"] > buckets[i]) & (df["gross_salary"] <= buckets[i + 1])])
            counts.append(count)
        sal_dist["labels"] = bucket_labels
        sal_dist["values"] = counts

    return {
        "monthly_trend": monthly_trend,
        "dept_cost": dept_cost,
        "statutory": statutory,
        "sal_dist": sal_dist,
    }


# ─────────────────────────────────────────────────────────────
# Payroll Reports
# ─────────────────────────────────────────────────────────────

def get_payroll_summary_report(filters: dict = None) -> list[dict]:
    """Monthly Payroll Summary – one row per (employee, month)."""
    df = _load_processed_payroll(filters)
    if df.empty:
        return []
    return df.to_dict(orient="records")


def get_department_payroll_report(filters: dict = None) -> list[dict]:
    """Department-wise aggregated payroll."""
    df = _load_processed_payroll(filters)
    if df.empty or "department" not in df.columns:
        return []

    agg = df.groupby("department").agg(
        employees=("employee_id", "nunique"),
        gross=("gross_salary", "sum"),
        net=("net_salary", "sum"),
        pf=("employee_pf", "sum"),
        esi=("esi_employee", "sum"),
        pt=("professional_tax", "sum"),
        tds=("tds", "sum"),
        employer_cost=("employer_cost", "sum"),
    ).reset_index()

    agg = agg.rename(columns={"department": "Department"})
    for col in ["gross", "net", "pf", "esi", "pt", "tds", "employer_cost"]:
        agg[col] = agg[col].round(2)

    return agg.to_dict(orient="records")


def get_employee_salary_history(employee_id: str = None, filters: dict = None) -> list[dict]:
    """Per-employee payroll history, optionally filtered."""
    all_filters = dict(filters or {})
    if employee_id:
        all_filters["employee_id"] = employee_id
    return get_payroll_summary_report(all_filters)


def get_contract_history(filters: dict = None) -> list[dict]:
    """All contracts joined with employee name."""
    df = read_csv(CSV_CONTRACTS)
    if df.empty:
        return []

    emp_df = read_csv(CSV_EMPLOYEES)
    if not emp_df.empty and "name" in emp_df.columns:
        df = pd.merge(df, emp_df[["employee_id", "name", "department"]], on="employee_id", how="left")

    # Apply simple filters
    if filters:
        if filters.get("employee_id"):
            df = df[df["employee_id"].str.contains(filters["employee_id"], case=False, na=False)]
        if filters.get("department") and "department" in df.columns:
            df = df[df["department"] == filters["department"]]

    return df.fillna("").to_dict(orient="records")


def get_fnf_report(filters: dict = None) -> list[dict]:
    """FnF Summary Report joined with employee details."""
    df = read_csv(CSV_FNF)
    if df.empty:
        return []

    emp_df = read_csv(CSV_EMPLOYEES)
    if not emp_df.empty:
        df = pd.merge(df, emp_df[["employee_id", "name", "department"]], on="employee_id", how="left")

    if filters:
        if filters.get("employee_id"):
            df = df[df["employee_id"].str.contains(filters["employee_id"], case=False, na=False)]
        if filters.get("department") and "department" in df.columns:
            df = df[df["department"] == filters["department"]]

    return df.fillna("").to_dict(orient="records")


# ─────────────────────────────────────────────────────────────
# Statutory Reports
# ─────────────────────────────────────────────────────────────

_STATUTORY_COL_MAP = {
    "pf": {"emp": "employee_pf", "er": "pf_employer", "label": "Provident Fund"},
    "esi": {"emp": "esi_employee", "er": "esi_employer", "label": "ESI"},
    "pt": {"emp": "professional_tax", "er": None, "label": "Professional Tax"},
    "lwf": {"emp": "lwf", "er": None, "label": "Labour Welfare Fund"},
    "tds": {"emp": "tds", "er": None, "label": "TDS / Income Tax"},
}


def get_statutory_report(component: str, filters: dict = None) -> list[dict]:
    """Returns one row per employee with statutory deduction details."""
    df = _load_processed_payroll(filters)
    if df.empty:
        return []

    meta = _STATUTORY_COL_MAP.get(component, {})
    emp_col = meta.get("emp")
    er_col = meta.get("er")

    keep_cols = ["employee_id", "name", "department", "month", "financial_year", "batch_id"]
    if emp_col and emp_col in df.columns:
        keep_cols.append(emp_col)
    if er_col and er_col in df.columns:
        keep_cols.append(er_col)

    result_df = df[[c for c in keep_cols if c in df.columns]].copy()
    return result_df.to_dict(orient="records")


def get_unique_departments_for_reports() -> list[str]:
    df = read_csv(CSV_EMPLOYEES)
    if df.empty or "department" not in df.columns:
        return []
    return sorted([d for d in df["department"].dropna().unique() if d])


def get_all_batches_for_reports() -> list[dict]:
    df = read_csv(CSV_PAYROLL_BATCHES)
    if df.empty:
        return []
    return df[["batch_id", "financial_year", "month", "status"]].fillna("").to_dict(orient="records")


def get_unique_employees_for_reports() -> list[dict]:
    df = read_csv(CSV_EMPLOYEES)
    if df.empty:
        return []
    return df[["employee_id", "name"]].fillna("").to_dict(orient="records")


# ─────────────────────────────────────────────────────────────
# Export Utilities
# ─────────────────────────────────────────────────────────────

def export_report_excel(data: list[dict], title: str = "Report") -> bytes:
    if not data:
        df = pd.DataFrame()
    else:
        df = pd.DataFrame(data)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=title[:31])
    return buf.getvalue()


def export_report_csv(data: list[dict]) -> bytes:
    if not data:
        df = pd.DataFrame()
    else:
        df = pd.DataFrame(data)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()
