"""
salary_routes.py – Flask routes for Phase 2: Salary Components & Structures.

Blueprint prefix: /hr/salary
All routes are HR-only.
"""

from fastapi import Request

from app.base.utils.flask_compat import Blueprint, render_template, session, redirect, url_for, flash, jsonify
from functools import wraps

from app.base.utils.config import CURRENT_FY
from app.payroll.services.salary_component_service import (
    get_all_components, get_component_by_id, create_component,
    update_component, toggle_component_active, delete_component,
    get_component_stats, get_all_codes,
)
from app.payroll.services.structure_service import (
    get_all_structures, get_structure_by_id, create_structure,
    update_structure, archive_structure, get_structure_components,
    add_component_to_structure, remove_component_from_structure,
    compute_preview, get_structure_stats, get_structures_for_dropdown,
)

salary_bp = Blueprint("salary", __name__, url_prefix="/hr/salary")


# ─────────────────────────────────────────────────────────────
# Auth guard
# ─────────────────────────────────────────────────────────────

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


# ═══════════════════════════════════════════════════════════════
# SALARY COMPONENTS
# ═══════════════════════════════════════════════════════════════

@salary_bp.route("/components")
@hr_required
async def list_components(request: Request):
    user = session["user"]
    search = request.query_params.get("search", "").strip()
    category_filter = request.query_params.get("category", "").strip()
    active_filter = request.query_params.get("active", "").strip()

    active_only = active_filter == "Yes"
    components = get_all_components(
        category=category_filter if category_filter else None,
        active_only=active_only,
        search=search if search else None,
    )
    stats = get_component_stats()

    return render_template(
        "hr/salary/components_list.html",
        user=user,
        components=components,
        stats=stats,
        search=search,
        category_filter=category_filter,
        active_filter=active_filter,
        fy=CURRENT_FY,
        active_page="salary_components",
    )


@salary_bp.route("/components/new", methods=["GET", "POST"])
@hr_required
async def new_component(request: Request):
    user = session["user"]
    all_codes = get_all_codes()

    if request.method == "POST":
        form = await request.form()
        data = {
            "name": form.get("name", "").strip(),
            "code": form.get("code", "").strip(),
            "category": form.get("category", "Earning").strip(),
            "computation_type": form.get("computation_type", "Fixed").strip(),
            "amount": form.get("amount", "0").strip(),
            "percentage": form.get("percentage", "0").strip(),
            "percentage_of": form.get("percentage_of", "").strip(),
            "formula": form.get("formula", "").strip(),
            "sequence": form.get("sequence", "100").strip(),
            "taxable": form.get("taxable", "No").strip(),
            "description": form.get("description", "").strip(),
        }
        res = create_component(data)
        if res["status"] == "success":
            flash(res["message"], "success")
            return redirect(url_for("salary.view_component", component_id=res["component_id"]))
        flash(res["message"], "danger")

    return render_template(
        "hr/salary/component_form.html",
        user=user,
        component=None,
        all_codes=all_codes,
        fy=CURRENT_FY,
        active_page="salary_components",
    )


@salary_bp.route("/components/<component_id>")
@hr_required
def view_component(component_id):
    user = session["user"]
    comp = get_component_by_id(component_id)
    if not comp:
        flash("Component not found.", "danger")
        return redirect(url_for("salary.list_components"))

    # Find structures that use this component
    from app.base.utils.config import CSV_STRUCTURE_COMPONENTS, CSV_SALARY_STRUCTURES
    from app.base.utils.csv_service import read_csv
    sc_df = read_csv(CSV_STRUCTURE_COMPONENTS)
    used_in = []
    if not sc_df.empty and "component_id" in sc_df.columns:
        links = sc_df[sc_df["component_id"] == component_id]
        if not links.empty:
            st_df = read_csv(CSV_SALARY_STRUCTURES)
            for _, row in links.iterrows():
                st_match = st_df[st_df["structure_id"] == row["structure_id"]]
                if not st_match.empty:
                    used_in.append(st_match.iloc[0].to_dict())

    return render_template(
        "hr/salary/component_detail.html",
        user=user,
        comp=comp,
        used_in=used_in,
        fy=CURRENT_FY,
        active_page="salary_components",
    )


@salary_bp.route("/components/<component_id>/edit", methods=["GET", "POST"])
@hr_required
async def edit_component(component_id, request: Request):
    user = session["user"]
    comp = get_component_by_id(component_id)
    if not comp:
        flash("Component not found.", "danger")
        return redirect(url_for("salary.list_components"))

    all_codes = [c for c in get_all_codes() if c != comp.get("code", "").upper()]

    if request.method == "POST":
        form = await request.form()
        data = {
            "name": form.get("name", "").strip(),
            "code": form.get("code", "").strip(),
            "category": form.get("category", "Earning").strip(),
            "computation_type": form.get("computation_type", "Fixed").strip(),
            "amount": form.get("amount", "0").strip(),
            "percentage": form.get("percentage", "0").strip(),
            "percentage_of": form.get("percentage_of", "").strip(),
            "formula": form.get("formula", "").strip(),
            "sequence": form.get("sequence", "100").strip(),
            "taxable": form.get("taxable", "No").strip(),
            "description": form.get("description", "").strip(),
        }
        res = update_component(component_id, data)
        if res["status"] == "success":
            flash(res["message"], "success")
            return redirect(url_for("salary.view_component", component_id=component_id))
        flash(res["message"], "danger")
        comp.update(data)

    return render_template(
        "hr/salary/component_form.html",
        user=user,
        component=comp,
        all_codes=all_codes,
        fy=CURRENT_FY,
        active_page="salary_components",
    )


@salary_bp.route("/components/<component_id>/toggle", methods=["POST"])
@hr_required
def toggle_component(component_id):
    res = toggle_component_active(component_id)
    flash(res["message"], "success" if res["status"] == "success" else "danger")
    return redirect(url_for("salary.view_component", component_id=component_id))


@salary_bp.route("/components/<component_id>/delete", methods=["POST"])
@hr_required
def remove_component(component_id):
    res = delete_component(component_id)
    if res["status"] == "success":
        flash(res["message"], "success")
        return redirect(url_for("salary.list_components"))
    flash(res["message"], "danger")
    return redirect(url_for("salary.view_component", component_id=component_id))


# ═══════════════════════════════════════════════════════════════
# SALARY STRUCTURES
# ═══════════════════════════════════════════════════════════════

@salary_bp.route("/structures")
@hr_required
async def list_structures(request: Request):
    user = session["user"]
    search = request.query_params.get("search", "").strip()
    type_filter = request.query_params.get("type", "").strip()
    active_filter = request.query_params.get("active", "").strip()

    structures = get_all_structures(
        active_only=(active_filter == "Yes"),
        search=search if search else None,
    )
    if type_filter:
        structures = [s for s in structures if s.get("structure_type") == type_filter]

    stats = get_structure_stats()

    return render_template(
        "hr/salary/structures_list.html",
        user=user,
        structures=structures,
        stats=stats,
        search=search,
        type_filter=type_filter,
        active_filter=active_filter,
        fy=CURRENT_FY,
        active_page="salary_structures",
    )


@salary_bp.route("/structures/new", methods=["GET", "POST"])
@hr_required
async def new_structure(request: Request):
    user = session["user"]
    if request.method == "POST":
        form = await request.form()
        data = {
            "name": form.get("name", "").strip(),
            "structure_type": form.get("structure_type", "Employee").strip(),
            "payroll_frequency": form.get("payroll_frequency", "Monthly").strip(),
            "description": form.get("description", "").strip(),
        }
        res = create_structure(data)
        if res["status"] == "success":
            flash(res["message"], "success")
            return redirect(url_for("salary.view_structure", structure_id=res["structure_id"]))
        flash(res["message"], "danger")

    return render_template(
        "hr/salary/structure_form.html",
        user=user,
        structure=None,
        fy=CURRENT_FY,
        active_page="salary_structures",
    )


@salary_bp.route("/structures/<structure_id>")
@hr_required
def view_structure(structure_id):
    user = session["user"]
    structure = get_structure_by_id(structure_id)
    if not structure:
        flash("Salary structure not found.", "danger")
        return redirect(url_for("salary.list_structures"))

    linked_components = get_structure_components(structure_id)
    all_components = get_all_components(active_only=True)
    linked_ids = {c["component_id"] for c in linked_components}
    available_components = [c for c in all_components if c["component_id"] not in linked_ids]

    return render_template(
        "hr/salary/structure_detail.html",
        user=user,
        structure=structure,
        linked_components=linked_components,
        available_components=available_components,
        fy=CURRENT_FY,
        active_page="salary_structures",
    )


@salary_bp.route("/structures/<structure_id>/edit", methods=["GET", "POST"])
@hr_required
async def edit_structure(structure_id, request: Request):
    user = session["user"]
    structure = get_structure_by_id(structure_id)
    if not structure:
        flash("Salary structure not found.", "danger")
        return redirect(url_for("salary.list_structures"))

    if request.method == "POST":
        form = await request.form()
        data = {
            "name": form.get("name", "").strip(),
            "structure_type": form.get("structure_type", "Employee").strip(),
            "payroll_frequency": form.get("payroll_frequency", "Monthly").strip(),
            "description": form.get("description", "").strip(),
        }
        res = update_structure(structure_id, data)
        if res["status"] == "success":
            flash(res["message"], "success")
            return redirect(url_for("salary.view_structure", structure_id=structure_id))
        flash(res["message"], "danger")
        structure.update(data)

    return render_template(
        "hr/salary/structure_form.html",
        user=user,
        structure=structure,
        fy=CURRENT_FY,
        active_page="salary_structures",
    )


@salary_bp.route("/structures/<structure_id>/archive", methods=["POST"])
@hr_required
def toggle_archive_structure(structure_id):
    res = archive_structure(structure_id)
    flash(res["message"], "success" if res["status"] == "success" else "danger")
    return redirect(url_for("salary.view_structure", structure_id=structure_id))


@salary_bp.route("/structures/<structure_id>/components/add", methods=["POST"])
@hr_required
async def add_component(structure_id, request: Request):
    form = await request.form()
    component_id = form.get("component_id", "").strip()
    if not component_id:
        flash("Please select a component to add.", "warning")
        return redirect(url_for("salary.view_structure", structure_id=structure_id))
    res = add_component_to_structure(structure_id, component_id)
    flash(res["message"], "success" if res["status"] == "success" else "danger")
    return redirect(url_for("salary.view_structure", structure_id=structure_id))


@salary_bp.route("/structures/<structure_id>/components/<component_id>/remove", methods=["POST"])
@hr_required
def remove_structure_component(structure_id, component_id):
    res = remove_component_from_structure(structure_id, component_id)
    flash(res["message"], "success" if res["status"] == "success" else "danger")
    return redirect(url_for("salary.view_structure", structure_id=structure_id))


# ─────────────────────────────────────────────────────────────
# Salary Preview
# ─────────────────────────────────────────────────────────────

@salary_bp.route("/structures/<structure_id>/preview")
@hr_required
async def salary_preview(structure_id, request: Request):
    user = session["user"]
    structure = get_structure_by_id(structure_id)
    if not structure:
        flash("Structure not found.", "danger")
        return redirect(url_for("salary.list_structures"))

    try:
        basic = float(request.query_params.get("basic", 0))
        gross = float(request.query_params.get("gross", 0))
    except (ValueError, TypeError):
        basic = 0.0
        gross = 0.0

    preview = compute_preview(structure_id, basic_salary=basic, gross_override=gross)

    return render_template(
        "hr/salary/salary_preview.html",
        user=user,
        structure=structure,
        preview=preview,
        basic_input=basic,
        gross_input=gross,
        fy=CURRENT_FY,
        active_page="salary_structures",
    )


@salary_bp.route("/structures/<structure_id>/preview/json")
@hr_required
async def salary_preview_json(structure_id, request: Request):
    """JSON API for AJAX-powered live preview updates."""
    try:
        basic = float(request.query_params.get("basic", 0))
        gross = float(request.query_params.get("gross", 0))
    except (ValueError, TypeError):
        basic = 0.0
        gross = 0.0

    preview = compute_preview(structure_id, basic_salary=basic, gross_override=gross)
    return jsonify(preview)
