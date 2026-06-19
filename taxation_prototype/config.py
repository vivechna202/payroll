"""
Configuration for the Taxation Prototype.
Phase 1: Setup & Scaffolding only.

Future Integration Points:
- Replace CSV_BASE_DIR with PostgreSQL connection string
- Add Alembic migration config
- Add cloud storage for file uploads
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# ──────────────────────────────────────────────
# Flask
# ──────────────────────────────────────────────
SECRET_KEY = "taxation-prototype-secret-key-change-in-prod"
DEBUG = True

# ──────────────────────────────────────────────
# Filesystem paths
# ──────────────────────────────────────────────
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
GENERATED_FOLDER = os.path.join(BASE_DIR, "generated")
FORM16_FOLDER = os.path.join(GENERATED_FOLDER, "form16")
FORM24Q_FOLDER = os.path.join(GENERATED_FOLDER, "form24q")
DUMMY_DATA_FOLDER = os.path.join(BASE_DIR, "dummy_data")
CSI_FOLDER = os.path.join(UPLOAD_FOLDER, "csi")
FORM16_PROCESSING_FOLDER = os.path.join(UPLOAD_FOLDER, "form16_processing")
# ──────────────────────────────────────────────
# CSV file paths  (swap with DB tables in Phase 2)
# ──────────────────────────────────────────────
CSV_EMPLOYEES           = os.path.join(DUMMY_DATA_FOLDER, "employees.csv")
CSV_DECLARATIONS        = os.path.join(DUMMY_DATA_FOLDER, "declarations.csv")
CSV_DECLARATION_ITEMS   = os.path.join(DUMMY_DATA_FOLDER, "declaration_items.csv")
CSV_PROOFS              = os.path.join(DUMMY_DATA_FOLDER, "proofs.csv")
CSV_PAYROLL             = os.path.join(DUMMY_DATA_FOLDER, "payroll.csv")
CSV_EMPLOYEE_SALARY     = os.path.join(DUMMY_DATA_FOLDER, "employee_salary.csv")
CSV_TDS                 = os.path.join(DUMMY_DATA_FOLDER, "tds.csv")
CSV_DECLARATION_WINDOWS = os.path.join(DUMMY_DATA_FOLDER, "declaration_windows.csv")
CSV_FORM16              = os.path.join(DUMMY_DATA_FOLDER, "form16.csv")
CSV_FORM16_HISTORY      = os.path.join(DUMMY_DATA_FOLDER, "form16_history.csv")
CSV_FORM24Q_HISTORY     = os.path.join(DUMMY_DATA_FOLDER, "form24q_history.csv")

CSV_CHALLANS                = os.path.join(DUMMY_DATA_FOLDER, "challans.csv")
CSV_DEDUCTOR_MASTER         = os.path.join(DUMMY_DATA_FOLDER, "deductor_master.csv")
CSV_FORM16_PROCESSING_LOG   = os.path.join(DUMMY_DATA_FOLDER, "form16_processing_log.csv")


# ──────────────────────────────────────────────
# Dummy authentication (hardcoded for Phase 1)
# Replace with DB-backed auth in Phase 2
# ──────────────────────────────────────────────
DUMMY_USERS = {
    "emp001": {
        "password": "emp@123",
        "role": "employee",
        "name": "Priya Sharma",
        "employee_id": "EMP001",
    },
    "hr001": {
        "password": "hr@123",
        "role": "hr",
        "name": "Rahul Verma",
        "employee_id": "HR001",
    },
}

# ──────────────────────────────────────────────
# Financial Year & Payroll Rules
# ──────────────────────────────────────────────
CURRENT_FY = "2024-25"
PF_PERCENTAGE = 12.0
PROFESSIONAL_TAX = 200.0

# ──────────────────────────────────────────────
# Tax Rules (Phase 5)
# ──────────────────────────────────────────────
STANDARD_DEDUCTION = 50000

TAX_SLABS_OLD = [
    {"limit": 250000, "rate": 0.0},
    {"limit": 500000, "rate": 0.05},
    {"limit": 1000000, "rate": 0.20},
    {"limit": float('inf'), "rate": 0.30}
]

TAX_SLABS_NEW = [
    {"limit": 300000, "rate": 0.0},
    {"limit": 600000, "rate": 0.05},
    {"limit": 900000, "rate": 0.10},
    {"limit": 1200000, "rate": 0.15},
    {"limit": 1500000, "rate": 0.20},
    {"limit": float('inf'), "rate": 0.30}
]
