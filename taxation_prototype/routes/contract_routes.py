"""
contract_routes.py – Flask routes for the HR Employee Contracts module.
Supports listing, viewing, creating, editing, and transitioning contracts.
"""

from flask import Blueprint, render_template, session, redirect, url_for, flash, request
from functools import wraps
import math

from config import CSV_EMPLOYEES, CURRENT_FY
from services.csv_service import csv_to_records
from services.contract_service import (
    get_all_contracts, get_contract_by_id, create_contract,
    update_contract, set_contract_status
)
from services.structure_service import get_structures_for_dropdown

contract_bp = Blueprint("contracts", __name__, url_prefix="/hr/contracts")

def hr_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        if session["user"].get("role") != "hr":
            flash("HR access required.", "danger")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated

@contract_bp.route("/")
@hr_required
def list_contracts():
    user = session["user"]
    search = request.args.get("search", "").strip()
    status_filter = request.args.get("status", "").strip()
    type_filter = request.args.get("type", "").strip()
    
    # Pagination
    try:
        page = int(request.args.get("page", 1))
    except ValueError:
        page = 1
    per_page = 10
    
    contracts = get_all_contracts(search=search, status_filter=status_filter, type_filter=type_filter)
    total_records = len(contracts)
    total_pages = math.ceil(total_records / per_page) if total_records > 0 else 1
    
    if page < 1:
        page = 1
    elif page > total_pages:
        page = total_pages
        
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paginated_contracts = contracts[start_idx:end_idx]
    
    return render_template(
        "hr/contracts_list.html",
        user=user,
        contracts=paginated_contracts,
        search=search,
        status_filter=status_filter,
        type_filter=type_filter,
        page=page,
        total_pages=total_pages,
        total_records=total_records,
        fy=CURRENT_FY,
        active_page="employee_contracts"
    )

@contract_bp.route("/new", methods=["GET", "POST"])
@hr_required
def new_contract():
    user = session["user"]
    
    if request.method == "POST":
        data = {
            "employee_id": request.form.get("employee_id", "").strip(),
            "company": request.form.get("company", "TaxPro Corp").strip(),
            "contract_start_date": request.form.get("contract_start_date", "").strip(),
            "contract_end_date": request.form.get("contract_end_date", "").strip(),
            "salary_structure": request.form.get("salary_structure", "").strip(),
            "salary_structure_type": request.form.get("salary_structure_type", "Permanent").strip(),
            "work_schedule": request.form.get("work_schedule", "Standard 40 Hours/Week").strip(),
            "currency": request.form.get("currency", "INR").strip(),
            "basic_salary": request.form.get("basic_salary", "0").strip(),
            "gross_salary": request.form.get("gross_salary", "0").strip(),
            "status": request.form.get("status", "Draft").strip()
        }
        
        res = create_contract(data)
        if res["status"] == "success":
            flash(res["message"], "success")
            return redirect(url_for("contracts.view_contract", contract_id=res["contract_id"]))
        else:
            flash(res["message"], "danger")
            # Fall through to render with input data
            
    # Get all employees and available salary structures
    employees = csv_to_records(CSV_EMPLOYEES)
    employees = sorted(employees, key=lambda x: x.get("name", ""))
    salary_structures = get_structures_for_dropdown()

    return render_template(
        "hr/contract_form.html",
        user=user,
        employees=employees,
        contract=None,
        salary_structures=salary_structures,
        fy=CURRENT_FY,
        active_page="employee_contracts"
    )

@contract_bp.route("/<contract_id>")
@hr_required
def view_contract(contract_id):
    user = session["user"]
    contract = get_contract_by_id(contract_id)
    if not contract:
        flash("Contract not found.", "danger")
        return redirect(url_for("contracts.list_contracts"))
        
    return render_template(
        "hr/contract_detail.html",
        user=user,
        contract=contract,
        fy=CURRENT_FY,
        active_page="employee_contracts"
    )

@contract_bp.route("/<contract_id>/edit", methods=["GET", "POST"])
@hr_required
def edit_contract(contract_id):
    user = session["user"]
    contract = get_contract_by_id(contract_id)
    if not contract:
        flash("Contract not found.", "danger")
        return redirect(url_for("contracts.list_contracts"))
        
    if request.method == "POST":
        updates = {
            "company": request.form.get("company", "").strip(),
            "contract_start_date": request.form.get("contract_start_date", "").strip(),
            "contract_end_date": request.form.get("contract_end_date", "").strip(),
            "salary_structure": request.form.get("salary_structure", "").strip(),
            "salary_structure_type": request.form.get("salary_structure_type", "").strip(),
            "work_schedule": request.form.get("work_schedule", "").strip(),
            "currency": request.form.get("currency", "").strip(),
            "basic_salary": request.form.get("basic_salary", "0").strip(),
            "gross_salary": request.form.get("gross_salary", "0").strip(),
            "status": request.form.get("status", "").strip()
        }
        
        res = update_contract(contract_id, updates)
        if res["status"] == "success":
            flash(res["message"], "success")
            return redirect(url_for("contracts.view_contract", contract_id=contract_id))
        else:
            flash(res["message"], "danger")
            # Update contract dictionary in-memory for re-rendering
            contract.update(updates)
            
    # Get all employees and available salary structures
    employees = csv_to_records(CSV_EMPLOYEES)
    employees = sorted(employees, key=lambda x: x.get("name", ""))
    salary_structures = get_structures_for_dropdown()

    return render_template(
        "hr/contract_form.html",
        user=user,
        employees=employees,
        contract=contract,
        salary_structures=salary_structures,
        fy=CURRENT_FY,
        active_page="employee_contracts"
    )

@contract_bp.route("/<contract_id>/status", methods=["POST"])
@hr_required
def change_status(contract_id):
    new_status = request.form.get("status", "").strip()
    res = set_contract_status(contract_id, new_status)
    if res["status"] == "success":
        flash(res["message"], "success")
    else:
        flash(res["message"], "danger")
    return redirect(url_for("contracts.view_contract", contract_id=contract_id))
