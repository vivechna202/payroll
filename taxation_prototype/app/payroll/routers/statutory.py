from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.payroll.services import statutory_service

statutory_bp = Blueprint("statutory", __name__, url_prefix="/statutory")

@statutory_bp.route("/dashboard")
def dashboard():
    configs = statutory_service.get_all_configs()
    active_configs = [c for c in configs if c.get("enabled") == "Yes"]
    
    # We could also show recent payroll batch statutory totals here, 
    # but for now let's just pass the configs for a simple dashboard.
    return render_template("hr/statutory/statutory_dashboard.html", 
                           configs=configs, 
                           active_configs=active_configs)

@statutory_bp.route("/configs")
def list_configs():
    configs = statutory_service.get_all_configs()
    return render_template("hr/statutory/configs_list.html", configs=configs)

@statutory_bp.route("/configs/new", methods=["GET", "POST"])
def create_config():
    if request.method == "POST":
        rule_type = request.form.get("rule_type")
        state = request.form.get("state")
        enabled = request.form.get("enabled", "No")
        effective_from = request.form.get("effective_from")
        
        # Build parameters dict based on rule_type
        parameters = {}
        if rule_type == "PF":
            parameters = {
                "employee_rate": float(request.form.get("pf_employee_rate", 12.0)),
                "employer_rate": float(request.form.get("pf_employer_rate", 12.0)),
                "eps_rate": float(request.form.get("pf_eps_rate", 8.33)),
                "wage_ceiling": float(request.form.get("pf_wage_ceiling", 15000.0)),
                "respect_wage_ceiling": request.form.get("pf_respect_wage_ceiling") == "on",
                "enable_eps_split": request.form.get("pf_enable_eps_split") == "on"
            }
        elif rule_type == "ESI":
            parameters = {
                "employee_rate": float(request.form.get("esi_employee_rate", 0.75)),
                "employer_rate": float(request.form.get("esi_employer_rate", 3.25)),
                "wage_ceiling": float(request.form.get("esi_wage_ceiling", 21000.0))
            }
        # For PT and LWF, the params can be more complex (e.g. JSON slabs).
        # We'll expect them to be provided as JSON strings from the frontend for simplicity if needed,
        # or we build a simplified version. For enterprise, a raw JSON editor might suffice for slabs.
        elif rule_type in ["PT", "LWF"]:
            raw_params = request.form.get("raw_parameters", "{}")
            import json
            try:
                parameters = json.loads(raw_params)
            except json.JSONDecodeError:
                flash("Invalid JSON in parameters field.", "danger")
                return redirect(url_for("statutory.create_config"))
        
        result = statutory_service.create_config(rule_type, state, enabled, effective_from, parameters)
        if result["status"] == "success":
            flash(result["message"], "success")
            return redirect(url_for("statutory.list_configs"))
        else:
            flash(result["message"], "danger")
    
    return render_template("hr/statutory/config_form.html", config=None)

@statutory_bp.route("/configs/<config_id>/edit", methods=["GET", "POST"])
def edit_config(config_id):
    config = statutory_service.get_config_by_id(config_id)
    if not config:
        flash("Configuration not found.", "danger")
        return redirect(url_for("statutory.list_configs"))

    if request.method == "POST":
        enabled = request.form.get("enabled", "No")
        effective_from = request.form.get("effective_from")
        
        updates = {
            "enabled": enabled,
            "effective_from": effective_from
        }
        
        # Only updating parameters if it's PT or LWF via JSON, or simple fields for PF/ESI
        rule_type = config.get("rule_type")
        parameters = {}
        if rule_type == "PF":
            parameters = {
                "employee_rate": float(request.form.get("pf_employee_rate", 12.0)),
                "employer_rate": float(request.form.get("pf_employer_rate", 12.0)),
                "eps_rate": float(request.form.get("pf_eps_rate", 8.33)),
                "wage_ceiling": float(request.form.get("pf_wage_ceiling", 15000.0)),
                "respect_wage_ceiling": request.form.get("pf_respect_wage_ceiling") == "on",
                "enable_eps_split": request.form.get("pf_enable_eps_split") == "on"
            }
            updates["parameters_json"] = parameters
        elif rule_type == "ESI":
            parameters = {
                "employee_rate": float(request.form.get("esi_employee_rate", 0.75)),
                "employer_rate": float(request.form.get("esi_employer_rate", 3.25)),
                "wage_ceiling": float(request.form.get("esi_wage_ceiling", 21000.0))
            }
            updates["parameters_json"] = parameters
        elif rule_type in ["PT", "LWF"]:
            raw_params = request.form.get("raw_parameters", "{}")
            import json
            try:
                updates["parameters_json"] = json.loads(raw_params)
            except json.JSONDecodeError:
                flash("Invalid JSON in parameters field.", "danger")
                return redirect(url_for("statutory.edit_config", config_id=config_id))
        
        result = statutory_service.update_config(config_id, updates)
        if result["status"] == "success":
            flash(result["message"], "success")
            return redirect(url_for("statutory.list_configs"))
        else:
            flash(result["message"], "danger")
            
    return render_template("hr/statutory/config_form.html", config=config)

@statutory_bp.route("/configs/<config_id>/toggle", methods=["POST"])
def toggle_config(config_id):
    result = statutory_service.toggle_config(config_id)
    if result["status"] == "success":
        flash(result["message"], "success")
    else:
        flash(result["message"], "danger")
    return redirect(url_for("statutory.list_configs"))
