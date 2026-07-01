"""Employee profile route (shared ESS)."""
from flask import render_template, session, redirect, url_for, flash, request
from app.base.utils.config import CSV_EMPLOYEES, CURRENT_FY
from app.base.utils.csv_service import read_csv_row
from app.payroll.services.contract_service import get_active_contract, get_contracts_for_employee
from app.base.routers.blueprints import employee_bp, employee_required

@employee_bp.route("/profile")
@employee_required
def profile():
    user = session["user"]
    role = user.get("role")
    
    # Determine which employee profile to show
    target_employee_id = request.args.get("employee_id", "").strip()
    
    if role == "employee":
        # Employees can only view their own profile
        target_employee_id = user["employee_id"]
    elif role == "hr":
        # HR can view anyone's profile, but if not specified, default to their own
        if not target_employee_id:
            target_employee_id = user["employee_id"]
            
    # Fetch employee data
    from app.base.utils.csv_service import read_csv_row
    employee_data = read_csv_row(CSV_EMPLOYEES, "employee_id", target_employee_id)
    if not employee_data:
        flash(f"Employee {target_employee_id} not found.", "danger")
        return redirect(url_for("dashboard"))
        
    # Fetch active contract and history
    from app.payroll.services.contract_service import get_active_contract, get_contracts_for_employee
    active_contract = get_active_contract(target_employee_id)
    contract_history = get_contracts_for_employee(target_employee_id)
    
    return render_template(
        "employee_profile.html",
        user=user,
        employee=employee_data,
        active_contract=active_contract,
        contract_history=contract_history,
        fy=CURRENT_FY,
        active_page="my_profile" if role == "employee" else "employee_directory"
    )

