# TaxPro HRMS – Employee Taxation Prototype
### Phase 1: Project Scaffold, Navigation & CSV Storage

---

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run the development server
python app.py
```

Open **http://localhost:5050** in your browser.

### Demo Login Credentials

| Role     | Username | Password  |
|----------|----------|-----------|
| Employee | `emp001` | `emp@123` |
| HR       | `hr001`  | `hr@123`  |

> You can switch roles at any time using the **"Switch to HR View / Employee"** button in the sidebar — no re-login required during demos.

---

## Architecture Overview

```
taxation_prototype/
│
├── app.py                  ← Flask app factory, auth routes, blueprint registration
├── config.py               ← All paths, dummy users, FY constant
├── requirements.txt
│
├── services/               ← Business logic layer (stubs in Phase 1)
│   ├── csv_service.py      ← Generic pandas CSV read/write utilities
│   ├── payroll_service.py  ← Payroll computation stubs
│   ├── tax_service.py      ← TDS & regime calculation stubs
│   ├── proof_service.py    ← Proof upload/approval workflow stubs
│   └── form24q_service.py  ← Form 24Q generation stubs
│
├── routes/                 ← Flask Blueprints
│   ├── employee_routes.py  ← /employee/* — 4 pages
│   └── hr_routes.py        ← /hr/*       — 5 pages
│
├── templates/              ← Jinja2 HTML templates
│   ├── base.html           ← Sidebar layout, nav, flash messages
│   ├── login.html          ← Standalone login page
│   ├── dashboard.html      ← Unified dashboard (both roles)
│   ├── 404.html / 403.html
│   ├── employee/
│   │   ├── tax_dashboard.html
│   │   ├── investment_declaration.html
│   │   ├── proof_upload.html
│   │   └── form16_download.html
│   └── hr/
│       ├── payroll_processing.html
│       ├── monthly_tds.html
│       ├── proof_approval.html
│       ├── declaration_window.html
│       └── form24q.html
│
├── static/
│   ├── css/main.css        ← Reusable component classes
│   └── js/main.js          ← Minimal UX utilities
│
├── uploads/                ← Employee proof file uploads (gitignore in prod)
├── generated/
│   ├── form16/             ← Generated Form 16 PDFs
│   └── form24q/            ← Generated Form 24Q stub files
│
└── dummy_data/             ← CSV flat-file "database" (Phase 1 only)
    ├── employees.csv
    ├── declarations.csv
    ├── proofs.csv
    ├── payroll.csv
    ├── tds.csv
    ├── declaration_windows.csv
    └── form16.csv
```

---

## Technology Stack (Phase 1)

| Layer        | Technology                          |
|-------------|--------------------------------------|
| Backend     | Python 3.11+ · Flask 3.x             |
| Templates   | Jinja2 (bundled with Flask)          |
| Styling     | Tailwind CSS (CDN) + custom CSS      |
| Data        | pandas · CSV flat files              |
| Auth        | Flask session · hardcoded dummy users|
| File Upload | Local filesystem (`uploads/`)        |

---

## Navigation Map

### Employee Portal
| Page                    | Route                              | Template                            |
|-------------------------|------------------------------------|--------------------------------------|
| Tax Dashboard           | `/employee/tax-dashboard`          | `employee/tax_dashboard.html`        |
| Investment Declaration  | `/employee/investment-declaration` | `employee/investment_declaration.html` |
| Proof Upload            | `/employee/proof-upload`           | `employee/proof_upload.html`         |
| Form 16 Download        | `/employee/form16-download`        | `employee/form16_download.html`      |

### HR Portal
| Page                    | Route                       | Template                             |
|-------------------------|-----------------------------|---------------------------------------|
| Payroll Processing      | `/hr/payroll-processing`    | `hr/payroll_processing.html`          |
| Monthly TDS             | `/hr/monthly-tds`           | `hr/monthly_tds.html`                 |
| Proof Approval          | `/hr/proof-approval`        | `hr/proof_approval.html`              |
| Declaration Window      | `/hr/declaration-window`    | `hr/declaration_window.html`          |
| Form 24Q                | `/hr/form24q`               | `hr/form24q.html`                     |

---

## CSV Schema Reference

### employees.csv
`employee_id, name, email, department, designation, date_of_joining, pan, uan, bank_account, ifsc, ctc_annual, basic_monthly, hra_monthly, special_allowance, pf_employee, pf_employer, professional_tax, status`

### declarations.csv
`declaration_id, employee_id, fy, window_id, section_80c_pf, section_80c_ppf, section_80c_lic, section_80c_elss, section_80c_nsc, section_80c_home_loan, section_80c_tuition, section_80c_other, section_80d_self, section_80d_parents, hra_rent_paid, hra_landlord_pan, hra_city_metro, lta_amount, nps_80ccd, home_loan_interest_24b, submitted_on, status, approved_by, remarks`

### proofs.csv
`proof_id, employee_id, declaration_id, section, filename, original_name, submitted_on, status, reviewer, remarks, reviewed_on`

### payroll.csv
`payroll_id, employee_id, month, year, fy, gross_salary, basic, hra, special_allowance, pf_employee, pf_employer, professional_tax, tds, other_deductions, net_salary, processed_on, processed_by, status`

### tds.csv
`tds_id, employee_id, month, year, fy, taxable_income_ytd, tax_liability_ytd, tds_deducted, tds_deposited, challan_no, challan_date, bsr_code, status`

### declaration_windows.csv
`window_id, fy, window_type, start_date, end_date, created_by, created_on, status`

### form16.csv
`form16_id, employee_id, fy, generated_on, generated_by, filename, filepath, status`

---

## Phase 2 Integration Points

> These are the exact places where CSV logic must be replaced with PostgreSQL + SQLAlchemy.

### 1. Database Setup
- **Replace**: `dummy_data/*.csv` flat files
- **With**: PostgreSQL tables mapped via SQLAlchemy ORM models
- **File**: Create `models/` package with `Employee`, `Declaration`, `Proof`, `Payroll`, `TDS`, `DeclarationWindow`, `Form16` models
- **Migration tool**: Alembic (`alembic init alembic` → write migration scripts)

```python
# config.py — replace CSV paths with:
SQLALCHEMY_DATABASE_URI = "postgresql://user:pass@localhost/taxpro_hrms"
```

### 2. CSV Service → ORM Queries
- **File**: `services/csv_service.py`
- **Action**: Replace `pd.read_csv()` calls with `db.session.query(Model).filter(...)` calls
- **Callers**: All service files (`payroll_service.py`, `tax_service.py`, etc.) use DataFrames — convert to ORM objects or keep converting to dicts for minimal template changes.

### 3. Authentication
- **Replace**: `DUMMY_USERS` dict in `config.py`
- **With**: `flask-login` + hashed passwords in `employees` table
- **File**: `routes/auth_routes.py` (new) + `models/user.py`

### 4. Payroll Engine
- **File**: `services/payroll_service.py`
- **Implement**: `process_monthly_payroll()` — gross-to-net computation, PF, PT, TDS
- **Trigger**: After payroll run, update `payroll` table and recalculate `tds` table

### 5. Tax Calculation Engine
- **File**: `services/tax_service.py`
- **Implement**: `get_employee_tax_summary()` — Old vs New Regime slab computation
- **Depends on**: Approved declarations + salary components from payroll

### 6. Proof Approval → TDS Recalculation
- **File**: `services/proof_service.py` → `approve_proof()`
- **Add**: After approval, call `tax_service.compute_tds_for_month()` to update TDS

### 7. Form 24Q – NSDL FVU Generation
- **File**: `services/form24q_service.py` → `generate_form24q()`
- **Implement**: NSDL-compliant fixed-width .fvu file format
- **Tool**: NSDL RPU (Return Preparation Utility) validation

### 8. Form 16 PDF Generation
- **New file**: `services/form16_service.py`
- **Library**: `reportlab` or `WeasyPrint`
- **Trigger**: After FY close, HR generates Form 16 for all employees

### 9. Cloud File Storage
- **Replace**: `uploads/` local directory
- **With**: AWS S3 / Google Cloud Storage using `boto3` / `google-cloud-storage`
- **File**: `services/storage_service.py` (new)

### 10. Background Jobs
- **Add**: Celery + Redis for:
  - Monthly payroll run
  - TDS reminders
  - Declaration window open/close
  - Form 16 batch generation
  - Email notifications

---

## Phase Roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| **Phase 1** | Project structure, CSV storage, routing, UI scaffold, dummy auth | ✅ **Complete** |
| **Phase 2** | PostgreSQL + Alembic, payroll engine, TDS logic, Flask-Login | ⬜ Planned |
| **Phase 3** | Form 16 PDF, Form 24Q FVU, proof approval → TDS recalculation | ⬜ Planned |
| **Phase 4** | HRMS integration, cloud storage, email notifications, Celery jobs | ⬜ Planned |

---

## Development Notes

- All CSV files are auto-created with headers on first run (`app.py` → `ensure_csv()`)
- Sample employee data (5 records) is seeded automatically if `employees.csv` is empty
- The `uploads/`, `generated/`, and `dummy_data/` directories are created automatically
- Add these to `.gitignore` for production: `uploads/`, `generated/`, `dummy_data/`, `venv/`, `__pycache__/`

---

*TaxPro HRMS · Phase 1 Prototype · Built with Flask + pandas + Tailwind CSS*
