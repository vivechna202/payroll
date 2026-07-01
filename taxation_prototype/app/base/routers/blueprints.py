"""Shared HR blueprint and auth decorator."""
from flask import Blueprint, session, redirect, url_for, flash
from functools import wraps

hr_bp = Blueprint("hr", __name__, url_prefix="/hr")


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


employee_bp = Blueprint("employee", __name__, url_prefix="/employee")


def employee_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login"))
        if session["user"].get("role") not in ("employee", "hr"):
            flash("Access denied.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated
