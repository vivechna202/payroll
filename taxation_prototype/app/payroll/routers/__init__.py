from app.payroll.routers.contracts import contract_bp
from app.payroll.routers.salary import salary_bp
from app.payroll.routers.payroll_engine import payroll_engine_bp
from app.payroll.routers.statutory import statutory_bp
from app.payroll.routers.payslips import payslips_bp
from app.payroll.routers.fnf import fnf_bp
from app.payroll.routers.reports import reports_bp

__all__ = [
    "contract_bp",
    "salary_bp",
    "payroll_engine_bp",
    "statutory_bp",
    "payslips_bp",
    "fnf_bp",
    "reports_bp",
]
