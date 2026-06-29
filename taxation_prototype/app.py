"""
app.py – Application entry point for the Employee Taxation Prototype.

Run:
    python app.py

Phase 2 Integration Points:
  - Replace CSV initialisation with Alembic migrations + PostgreSQL.
  - Add Flask-Login for production-grade auth.
  - Add Celery for async payroll / TDS computation jobs.
"""

import os
from flask import Flask, render_template, session, redirect, url_for, request, flash, send_from_directory, abort , jsonify
from config import (
    SECRET_KEY, DEBUG, UPLOAD_FOLDER, GENERATED_FOLDER,
    FORM16_FOLDER, FORM24Q_FOLDER, DUMMY_DATA_FOLDER,
    CSV_EMPLOYEES, CSV_DECLARATIONS, CSV_DECLARATION_ITEMS, CSV_PROOFS, CSV_PAYROLL, CSV_EMPLOYEE_SALARY,
    CSV_TDS, CSV_DECLARATION_WINDOWS, CSV_FORM16, CSV_FORM16_HISTORY,
    DUMMY_USERS, CURRENT_FY, CSV_CHALLANS, CSV_DEDUCTOR_MASTER, CSI_FOLDER,
    FORM16_PROCESSING_FOLDER, CSV_FORM16_PROCESSING_LOG, FORM16_MERGED_FOLDER, FORM16_SIGNED_FOLDER,
    CSV_CONTRACTS,
    CSV_SALARY_COMPONENTS, CSV_SALARY_STRUCTURES, CSV_STRUCTURE_COMPONENTS,
    CSV_PAYROLL_BATCHES, PAYROLL_DEFAULT_PAYABLE_DAYS, CSV_STATUTORY_CONFIG, CSV_PAYSLIPS, CSV_FNF
)
from services.csv_service import ensure_csv

# ─────────────────────────────────────────────────────────────
# App factory
# ─────────────────────────────────────────────────────────────

app = Flask(__name__)
app.secret_key = SECRET_KEY
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5 MB

# ─────────────────────────────────────────────────────────────
# Ensure directories exist
# ─────────────────────────────────────────────────────────────

for _dir in [UPLOAD_FOLDER, GENERATED_FOLDER, FORM16_FOLDER,
             FORM24Q_FOLDER, DUMMY_DATA_FOLDER, CSI_FOLDER,
             FORM16_PROCESSING_FOLDER, FORM16_MERGED_FOLDER, FORM16_SIGNED_FOLDER]:
    os.makedirs(_dir, exist_ok=True)

# ─────────────────────────────────────────────────────────────
# Initialise CSV files with headers (idempotent)
# ─────────────────────────────────────────────────────────────

ensure_csv(CSV_EMPLOYEES, [
    "employee_id", "name", "email", "department", "designation",
    "date_of_joining", "pan", "uan", "bank_account", "ifsc", "status", "state",
])

ensure_csv(CSV_DECLARATIONS, [
    "declaration_id", "employee_id", "financial_year", "tax_regime", 
    "status", "submitted_at", "updated_at"
])

ensure_csv(CSV_DECLARATION_ITEMS, [
    "declaration_id", "section", "amount"
])

ensure_csv(CSV_PROOFS, [
    "proof_id", "employee_id", "declaration_id", "section",
    "file_name", "file_path", "status", "hr_remarks",
    "uploaded_at", "reviewed_at", "reviewed_by"
])

ensure_csv(CSV_PAYROLL, [
    "payroll_id", "employee_id", "financial_year", "month",
    "basic_salary", "hra", "special_allowance", "other_allowances",
    "gross_salary", "employee_pf", "professional_tax", "tds", "net_salary",
    "payroll_status", "processed_at",
    "batch_id", "payable_days", "lop_days", "lop_amount",
    "overtime_hours", "overtime_amount",
    "pf_employee", "pf_employer", "esi_employee", "esi_employer",
    "pt", "lwf", "bonus", "incentives",
    "earnings_json", "deductions_json", "processed_by"
])

ensure_csv(CSV_EMPLOYEE_SALARY, [
    "employee_id", "basic_salary", "hra", "special_allowance",
    "other_allowances", "effective_from",
    "tds_regime", "section_80C", "section_80D", "hra_exemption"
])

ensure_csv(CSV_TDS, [
    "tds_id", "employee_id", "financial_year", "month", "tax_regime",
    "annual_taxable_income", "estimated_annual_tax", "annual_tds",
    "monthly_tds", "payroll_id", "calculated_at"
])

ensure_csv(CSV_DECLARATION_WINDOWS, [
    "window_id", "fy", "window_type", "start_date",
    "end_date", "created_by", "created_on", "status",
])

ensure_csv(CSV_FORM16, [
    "form16_id", "employee_id", "fy", "generated_on",
    "generated_by", "filename", "filepath", "status",
])

ensure_csv(CSV_FORM16_HISTORY, [
    "generation_id", "employee_id", "financial_year",
    "generated_by", "generated_at", "file_name"
])

# Form 16 Processing audit log (separate from existing Form 16 module)
ensure_csv(CSV_FORM16_PROCESSING_LOG, [
    "log_id", "session_id", "event_type", "filename",
    "status", "pan", "employee_name", "financial_year",
    "part_type", "error_detail", "timestamp"
])

from config import CSV_FORM24Q_HISTORY
ensure_csv(CSV_FORM24Q_HISTORY, [
    "generation_id", "financial_year", "quarter", "generated_by",
    "generated_at", "file_name"
])

ensure_csv(CSV_CHALLANS, [
    "challan_id",
    "quarter",
    "financial_year",
    "bsr_code",
    "challan_serial_no",
    "challan_date",
    "challan_amount",
    "section_code",
    "status"
])

ensure_csv(CSV_DEDUCTOR_MASTER, [
    "tan",
    "pan",
    "company_name",
    "address",
    "state",
    "pin_code",
    "contact_person",
    "contact_email"
])

ensure_csv(CSV_CONTRACTS, [
    "contract_id",
    "employee_id",
    "employee_name",
    "department",
    "designation",
    "company",
    "joining_date",
    "contract_start_date",
    "contract_end_date",
    "salary_structure",
    "salary_structure_type",
    "work_schedule",
    "payroll_frequency",
    "currency",
    "basic_salary",
    "gross_salary",
    "status",
    "created_at",
    "updated_at"
])

ensure_csv(CSV_SALARY_COMPONENTS, [
    "component_id", "name", "code", "category", "computation_type",
    "amount", "percentage", "percentage_of", "formula",
    "sequence", "taxable", "active", "description", "created_at", "updated_at"
])

ensure_csv(CSV_SALARY_STRUCTURES, [
    "structure_id", "name", "structure_type", "payroll_frequency",
    "description", "active", "created_at", "updated_at"
])

ensure_csv(CSV_STRUCTURE_COMPONENTS, [
    "id", "structure_id", "component_id", "override_amount", "override_percentage", "added_at"
])

ensure_csv(CSV_PAYROLL_BATCHES, [
    "batch_id", "month", "month_name", "year", "financial_year",
    "payroll_frequency", "description", "status", "locked",
    "employee_count", "error_count", "total_gross", "total_deductions",
    "total_employer_cost", "total_net", "total_tds",
    "created_by", "created_at", "processed_by", "processed_at",
    "locked_by", "locked_at", "updated_at"
])

ensure_csv(CSV_STATUTORY_CONFIG, [
    "config_id", "rule_type", "state", "enabled", "effective_from", "parameters_json", "created_at", "updated_at"
])

ensure_csv(CSV_PAYSLIPS, [
    "payslip_id", "payroll_id", "employee_id", "financial_year", "month",
    "status", "remarks", "created_by", "created_at",
    "confirmed_by", "confirmed_at", "paid_by", "paid_at"
])

ensure_csv(CSV_FNF, [
    "settlement_id", "employee_id", "last_working_date", "status",
    "pending_salary", "notice_period_amount", "leave_encashment", "gratuity",
    "bonus_incentives", "other_recoveries", "total_earnings", "total_deductions",
    "net_payable", "remarks", "created_by", "created_at",
    "approved_by", "approved_at", "paid_by", "paid_at"
])


# ─────────────────────────────────────────────────────────────
# Seed Phase 2: Salary Components & Structures (if empty)
# ─────────────────────────────────────────────────────────────

import pandas as pd  # noqa: E402 – required here for seeding
_comp_df = pd.read_csv(CSV_SALARY_COMPONENTS, dtype=str).fillna("")
if _comp_df.empty:
    from datetime import datetime as _dt

    _now = _dt.now().isoformat()
    _components = [
        {"component_id": "COMP-BASIC",     "name": "Basic Salary",          "code": "BASIC",      "category": "Earning",   "computation_type": "Fixed",      "amount": "0",    "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "10",  "taxable": "Yes", "active": "Yes", "description": "Fixed basic salary",                          "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-HRA",       "name": "House Rent Allowance",  "code": "HRA",        "category": "Earning",   "computation_type": "Percentage", "amount": "",    "percentage": "40",  "percentage_of": "BASIC",  "formula": "", "sequence": "20",  "taxable": "Yes", "active": "Yes", "description": "40% of Basic (metro cities)",                 "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-DA",        "name": "Dearness Allowance",    "code": "DA",         "category": "Earning",   "computation_type": "Fixed",      "amount": "0",    "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "30",  "taxable": "Yes", "active": "Yes", "description": "Dearness allowance",                          "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-SPECIAL",   "name": "Special Allowance",     "code": "SPECIAL",    "category": "Earning",   "computation_type": "Fixed",      "amount": "0",    "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "40",  "taxable": "Yes", "active": "Yes", "description": "Special allowance / balancing component",      "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-CONV",      "name": "Conveyance Allowance",  "code": "CONVEYANCE", "category": "Earning",   "computation_type": "Fixed",      "amount": "1600", "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "50",  "taxable": "No",  "active": "Yes", "description": "Conveyance / transport allowance",            "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-MED",       "name": "Medical Allowance",     "code": "MEDICAL",    "category": "Earning",   "computation_type": "Fixed",      "amount": "1250", "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "60",  "taxable": "No",  "active": "Yes", "description": "Medical reimbursement allowance",             "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-BONUS",     "name": "Performance Bonus",    "code": "BONUS",      "category": "Earning",   "computation_type": "Fixed",      "amount": "0",    "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "70",  "taxable": "Yes", "active": "Yes", "description": "Performance-linked bonus",                    "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-INCENT",    "name": "Incentives",            "code": "INCENTIVE",  "category": "Earning",   "computation_type": "Fixed",      "amount": "0",    "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "80",  "taxable": "Yes", "active": "Yes", "description": "Sales / performance incentives",              "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-PF",        "name": "Provident Fund",        "code": "PF",         "category": "Deduction", "computation_type": "Percentage", "amount": "",    "percentage": "12",  "percentage_of": "BASIC",  "formula": "", "sequence": "110", "taxable": "No",  "active": "Yes", "description": "Employee PF contribution – 12% of Basic",     "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-ESI",       "name": "ESI",                   "code": "ESI",        "category": "Deduction", "computation_type": "Formula",    "amount": "",    "percentage": "",   "percentage_of": "",      "formula": "round(GROSS * 0.0075, 2) if GROSS <= 21000 else 0", "sequence": "120", "taxable": "No",  "active": "Yes", "description": "ESI – 0.75% of gross (only if gross ≤ ₹21,000)","created_at": _now, "updated_at": _now},
        {"component_id": "COMP-PT",        "name": "Professional Tax",      "code": "PT",         "category": "Deduction", "computation_type": "Fixed",      "amount": "200",  "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "130", "taxable": "No",  "active": "Yes", "description": "State professional tax (flat ₹200/month)",   "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-LWF",       "name": "Labour Welfare Fund",   "code": "LWF",        "category": "Deduction", "computation_type": "Fixed",      "amount": "20",   "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "140", "taxable": "No",  "active": "Yes", "description": "LWF employee contribution",                  "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-LOAN",      "name": "Loan Recovery",         "code": "LOAN",       "category": "Deduction", "computation_type": "Fixed",      "amount": "0",    "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "150", "taxable": "No",  "active": "Yes", "description": "Salary advance / loan recovery",             "created_at": _now, "updated_at": _now},
        {"component_id": "COMP-TDS",       "name": "TDS (Placeholder)",     "code": "TDS",        "category": "Deduction", "computation_type": "Fixed",      "amount": "0",    "percentage": "",   "percentage_of": "",      "formula": "", "sequence": "160", "taxable": "No",  "active": "Yes", "description": "TDS – computed in payroll phase",            "created_at": _now, "updated_at": _now},
    ]
    pd.DataFrame(_components).to_csv(CSV_SALARY_COMPONENTS, index=False)

    _structures = [{
        "structure_id": "SS-001",
        "name": "Standard Monthly Structure",
        "structure_type": "Employee",
        "payroll_frequency": "Monthly",
        "description": "Default structure for permanent employees",
        "active": "Yes",
        "created_at": _now,
        "updated_at": _now,
    }]
    pd.DataFrame(_structures).to_csv(CSV_SALARY_STRUCTURES, index=False)

    import uuid as _uuid
    _sc_rows = [
        {"id": str(_uuid.uuid4()), "structure_id": "SS-001", "component_id": c["component_id"],
         "override_amount": "", "override_percentage": "", "added_at": _now}
        for c in _components
    ]
    pd.DataFrame(_sc_rows).to_csv(CSV_STRUCTURE_COMPONENTS, index=False)


# ─────────────────────────────────────────────────────────────
# Seed sample employee records (only if employees.csv is empty)
# ─────────────────────────────────────────────────────────────


_emp_df = pd.read_csv(CSV_EMPLOYEES, dtype=str).fillna("")
if _emp_df.empty:
    sample_employees = [
        {
            "employee_id": "EMP001", "name": "Priya Sharma",
            "email": "priya.sharma@company.com",
            "department": "Engineering", "designation": "Software Engineer",
            "date_of_joining": "2021-07-01", "pan": "ABCPS1234D",
            "uan": "100456789012", "bank_account": "9876543210",
            "ifsc": "SBIN0001234", "status": "ACTIVE",
        },
        {
            "employee_id": "EMP002", "name": "Arjun Mehta",
            "email": "arjun.mehta@company.com",
            "department": "Finance", "designation": "Financial Analyst",
            "date_of_joining": "2020-03-15", "pan": "BCDAM5678E",
            "uan": "100456789013", "bank_account": "8765432109",
            "ifsc": "HDFC0002345", "status": "ACTIVE",
        },
        {
            "employee_id": "EMP003", "name": "Sneha Iyer",
            "email": "sneha.iyer@company.com",
            "department": "HR", "designation": "HR Manager",
            "date_of_joining": "2019-11-01", "pan": "CDPSI9012F",
            "uan": "100456789014", "bank_account": "7654321098",
            "ifsc": "ICIC0003456", "status": "ACTIVE",
        },
        {
            "employee_id": "EMP004", "name": "Karan Gupta",
            "email": "karan.gupta@company.com",
            "department": "Sales", "designation": "Sales Executive",
            "date_of_joining": "2022-08-01", "pan": "DEPKG3456G",
            "uan": "100456789015", "bank_account": "6543210987",
            "ifsc": "AXIS0004567", "status": "ACTIVE",
        },
        {
            "employee_id": "HR001", "name": "Rahul Verma",
            "email": "rahul.verma@company.com",
            "department": "HR", "designation": "HR Director",
            "date_of_joining": "2018-01-10", "pan": "EFPRV7890H",
            "uan": "100456789016", "bank_account": "5432109876",
            "ifsc": "KOTAK0005678", "status": "ACTIVE",
        },
    ]
    pd.DataFrame(sample_employees).to_csv(CSV_EMPLOYEES, index=False)
    
    sample_salaries = [
        {"employee_id": "EMP001", "basic_salary": 50000, "hra": 20000, "special_allowance": 17000, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
        {"employee_id": "EMP002", "basic_salary": 37500, "hra": 15000, "special_allowance": 12000, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
        {"employee_id": "EMP003", "basic_salary": 62500, "hra": 25000, "special_allowance": 20833, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
        {"employee_id": "EMP004", "basic_salary": 25000, "hra": 10000, "special_allowance": 8000, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
        {"employee_id": "HR001", "basic_salary": 83333, "hra": 33333, "special_allowance": 27778, "other_allowances": 0, "effective_from": "2024-04-01", "tds_regime": "NEW", "section_80C": 0, "section_80D": 0, "hra_exemption": 0},
    ]
    pd.DataFrame(sample_salaries).to_csv(CSV_EMPLOYEE_SALARY, index=False)

# Update state for existing employees if blank
_emp_df = pd.read_csv(CSV_EMPLOYEES, dtype=str).fillna("")
if "state" in _emp_df.columns:
    state_map = {
        "EMP001": "Maharashtra",
        "EMP002": "Karnataka",
        "EMP003": "Delhi",
        "EMP004": "Tamil Nadu",
        "EMP005": "Maharashtra",
        "HR001": "Delhi"
    }
    updated = False
    for idx, row in _emp_df.iterrows():
        emp_id = row["employee_id"]
        if row["state"] == "" and emp_id in state_map:
            _emp_df.at[idx, "state"] = state_map[emp_id]
            updated = True
    if updated:
        _emp_df.to_csv(CSV_EMPLOYEES, index=False)

# Seed Statutory Configurations
import json
_stat_df = pd.read_csv(CSV_STATUTORY_CONFIG, dtype=str).fillna("")
if _stat_df.empty:
    _now = pd.Timestamp.now().isoformat()
    _configs = [
        {
            "config_id": "STAT-PF", "rule_type": "PF", "state": "All", "enabled": "Yes", "effective_from": "2024-04-01",
            "parameters_json": json.dumps({
                "employee_rate": 12.0, "employer_rate": 12.0, "eps_rate": 8.33, "epf_rate": 3.67,
                "wage_ceiling": 15000.0, "vpf_rate": 0.0, "enable_eps_split": True, "respect_wage_ceiling": True
            }),
            "created_at": _now, "updated_at": _now
        },
        {
            "config_id": "STAT-ESI", "rule_type": "ESI", "state": "All", "enabled": "Yes", "effective_from": "2024-04-01",
            "parameters_json": json.dumps({
                "employee_rate": 0.75, "employer_rate": 3.25, "wage_ceiling": 21000.0
            }),
            "created_at": _now, "updated_at": _now
        },
        {
            "config_id": "STAT-PT-MH", "rule_type": "PT", "state": "Maharashtra", "enabled": "Yes", "effective_from": "2024-04-01",
            "parameters_json": json.dumps({
                "slabs": [
                    {"min": 0, "max": 7500, "amount": 0.0},
                    {"min": 7500, "max": 10000, "amount": 175.0},
                    {"min": 10000, "max": 99999999, "amount": 200.0, "feb_amount": 250.0}
                ]
            }),
            "created_at": _now, "updated_at": _now
        },
        {
            "config_id": "STAT-PT-KA", "rule_type": "PT", "state": "Karnataka", "enabled": "Yes", "effective_from": "2024-04-01",
            "parameters_json": json.dumps({
                "slabs": [
                    {"min": 0, "max": 25000, "amount": 0.0},
                    {"min": 25000, "max": 99999999, "amount": 200.0}
                ]
            }),
            "created_at": _now, "updated_at": _now
        },
        {
            "config_id": "STAT-PT-TN", "rule_type": "PT", "state": "Tamil Nadu", "enabled": "Yes", "effective_from": "2024-04-01",
            "parameters_json": json.dumps({
                "slabs": [
                    {"min": 0, "max": 21000, "amount": 0.0},
                    {"min": 21000, "max": 30000, "amount": 100.0},
                    {"min": 30000, "max": 45000, "amount": 150.0},
                    {"min": 45000, "max": 99999999, "amount": 200.0}
                ]
            }),
            "created_at": _now, "updated_at": _now
        },
        {
            "config_id": "STAT-LWF-MH", "rule_type": "LWF", "state": "Maharashtra", "enabled": "Yes", "effective_from": "2024-04-01",
            "parameters_json": json.dumps({
                "employee_contribution": 25.0, "employer_contribution": 75.0, "deduction_months": [6, 12]
            }),
            "created_at": _now, "updated_at": _now
        },
        {
            "config_id": "STAT-LWF-KA", "rule_type": "LWF", "state": "Karnataka", "enabled": "Yes", "effective_from": "2024-04-01",
            "parameters_json": json.dumps({
                "employee_contribution": 20.0, "employer_contribution": 40.0, "deduction_months": [12]
            }),
            "created_at": _now, "updated_at": _now
        },
        {
            "config_id": "STAT-LWF-TN", "rule_type": "LWF", "state": "Tamil Nadu", "enabled": "Yes", "effective_from": "2024-04-01",
            "parameters_json": json.dumps({
                "employee_contribution": 10.0, "employer_contribution": 20.0, "deduction_months": [12]
            }),
            "created_at": _now, "updated_at": _now
        },
        {
            "config_id": "STAT-LWF-DL", "rule_type": "LWF", "state": "Delhi", "enabled": "Yes", "effective_from": "2024-04-01",
            "parameters_json": json.dumps({
                "employee_contribution": 0.75, "employer_contribution": 2.25, "deduction_months": [6, 12]
            }),
            "created_at": _now, "updated_at": _now
        }
    ]
    pd.DataFrame(_configs).to_csv(CSV_STATUTORY_CONFIG, index=False)


# ─────────────────────────────────────────────────────────────
# Register blueprints
# ─────────────────────────────────────────────────────────────

from routes.employee_routes import employee_bp
from routes.hr_routes import hr_bp
from routes.form16_processing_routes import form16_processing_bp
from routes.contract_routes import contract_bp
from routes.salary_routes import salary_bp
from routes.payroll_engine_routes import payroll_engine_bp
from routes.statutory_routes import statutory_bp
from routes.payslip_routes import payslips_bp
from routes.fnf_routes import fnf_bp
from routes.payroll_reports_routes import reports_bp
from routes.ess_routes import ess_bp
from routes.workflow_routes import workflow_bp, notifications_bp

from services.workflow_service import ensure_workflow_csvs
from services.notification_service import ensure_notifications_csv
ensure_workflow_csvs()
ensure_notifications_csv()

app.register_blueprint(employee_bp)
app.register_blueprint(hr_bp)
app.register_blueprint(form16_processing_bp)
app.register_blueprint(contract_bp)
app.register_blueprint(salary_bp)
app.register_blueprint(payroll_engine_bp)
app.register_blueprint(statutory_bp)
app.register_blueprint(payslips_bp)
app.register_blueprint(fnf_bp)
app.register_blueprint(reports_bp)
app.register_blueprint(ess_bp)
app.register_blueprint(workflow_bp)
app.register_blueprint(notifications_bp)


# Cleanup stale Form 16 Processing temp sessions on startup
from services.form16_processing_service import cleanup_stale_sessions
cleanup_stale_sessions(max_age_hours=24)

# ─────────────────────────────────────────────────────────────
# Auth routes
# ─────────────────────────────────────────────────────────────

@app.route("/", methods=["GET"])
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("auth.login"))


@app.route("/login", methods=["GET", "POST"])
def login_redirect():
    return redirect(url_for("auth.login"))


@app.route("/auth/login", methods=["GET", "POST"], endpoint="auth.login")
def auth_login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")
        user = DUMMY_USERS.get(username)
        if user and user["password"] == password:
            session["user"] = {
                "username": username,
                "role": user["role"],
                "name": user["name"],
                "employee_id": user["employee_id"],
            }
            flash(f"Welcome, {user['name']}!", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid credentials. Try emp001/emp@123 or hr001/hr@123", "danger")
    return render_template("login.html", title="Login – TaxPro HRMS")


@app.route("/auth/switch-role", methods=["POST"], endpoint="auth.switch_role")
def switch_role():
    """Demo convenience: switch between employee and HR views."""
    if "user" not in session:
        return redirect(url_for("auth.login"))
    target_role = request.form.get("role")
    for uname, udata in DUMMY_USERS.items():
        if udata["role"] == target_role:
            session["user"] = {
                "username": uname,
                "role": udata["role"],
                "name": udata["name"],
                "employee_id": udata["employee_id"],
            }
            flash(f"Switched to {target_role.upper()} view as {udata['name']}", "info")
            break
    return redirect(url_for("dashboard"))


@app.route("/auth/logout", endpoint="auth.logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("auth.login"))
    user = session["user"]
    employees = pd.read_csv(CSV_EMPLOYEES, dtype=str).fillna("").to_dict(orient="records")
    
    metrics = None
    if user["role"] == "hr":
        from services.tax_service import get_hr_dashboard_metrics
        metrics = get_hr_dashboard_metrics(CURRENT_FY)
        
    return render_template(
        "dashboard.html",
        user=user,
        employees=employees,
        metrics=metrics,
        fy=CURRENT_FY,
        active_page="dashboard",
    )


# ─────────────────────────────────────────────────────────────
# Error handlers
# ─────────────────────────────────────────────────────────────

@app.route("/uploads/<employee_id>/<filename>")
def serve_upload(employee_id, filename):
    if "user" not in session:
        return redirect(url_for("auth.login"))
        
    user = session["user"]
    # RBAC check: HR can see all, Employee can only see their own
    if user["role"] == "employee" and user["employee_id"] != employee_id:
        abort(403)
        
    employee_upload_dir = os.path.join(app.config["UPLOAD_FOLDER"], employee_id)
    return send_from_directory(employee_upload_dir, filename)


@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403


# ─────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=DEBUG, port=5050)
