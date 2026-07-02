"""Shared HR and employee routers (Flask Blueprint → FastAPI CompatRouter)."""
from app.base.utils.flask_compat import Blueprint, hr_required, employee_required

hr_bp = Blueprint("hr", __name__, url_prefix="/hr")
employee_bp = Blueprint("employee", __name__, url_prefix="/employee")

__all__ = ["hr_bp", "employee_bp", "hr_required", "employee_required"]
