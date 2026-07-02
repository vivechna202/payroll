"""
app/main.py – FastAPI application entry point for TaxPro HRMS.

Run:
    python app.py
    python -m app.main
    uvicorn app.main:app --reload --port 5050
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager


_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.base.utils.config import DEBUG, SECRET_KEY
from app.base.utils.flask_compat import RedirectException, render_template
from app.base.utils.startup import run_startup

_APP_DIR = os.path.dirname(os.path.abspath(__file__))


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_startup()
    from app.workflow.services.workflow_service import ensure_workflow_csvs
    from app.workflow.services.notification_service import ensure_notifications_csv
    from app.taxation.services.form16_processing_service import cleanup_stale_sessions

    ensure_workflow_csvs()
    ensure_notifications_csv()
    cleanup_stale_sessions(max_age_hours=24)
    yield


app = FastAPI(
    title="TaxPro HRMS",
    version="1.0.0",
    lifespan=lifespan,
    debug=DEBUG,
)

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, max_age=86400 * 7)

static_dir = os.path.join(_APP_DIR, "base", "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")


# ── Exception handlers (Flask errorhandler equivalent) ───────────────────

@app.exception_handler(RedirectException)
async def redirect_exception_handler(request: Request, exc: RedirectException):
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url=exc.url, status_code=exc.status_code)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code == 404:
        from app.base.utils.flask_compat import _current_request, _template_context, templates
        token = _current_request.set(request)
        try:
            html = templates.env.get_template("404.html").render(_template_context())
            return HTMLResponse(content=html, status_code=404)
        finally:
            _current_request.reset(token)
    if exc.status_code == 403:
        from app.base.utils.flask_compat import _current_request, _template_context, templates
        token = _current_request.set(request)
        try:
            html = templates.env.get_template("403.html").render(_template_context())
            return HTMLResponse(content=html, status_code=403)
        finally:
            _current_request.reset(token)
    from fastapi.responses import JSONResponse
    return JSONResponse(content={"detail": exc.detail}, status_code=exc.status_code)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    from app.base.utils.flask_compat import _current_request, _template_context, templates
    token = _current_request.set(request)
    try:
        html = templates.env.get_template("404.html").render(_template_context())
        return HTMLResponse(content=html, status_code=404)
    finally:
        _current_request.reset(token)


@app.exception_handler(403)
async def forbidden_handler(request: Request, exc):
    from app.base.utils.flask_compat import _current_request, _template_context, templates
    token = _current_request.set(request)
    try:
        html = templates.env.get_template("403.html").render(_template_context())
        return HTMLResponse(content=html, status_code=403)
    finally:
        _current_request.reset(token)


# ── Register routers (Flask blueprint → FastAPI APIRouter) ───────────────

def _register_routers():
    from importlib import import_module
    from app.base.routers.blueprints import employee_bp, hr_bp
    from app.base.routers.pages import router as pages_router
    from app.taxation.routers.form16_processing import form16_processing_bp
    from app.payroll.routers.contracts import contract_bp
    from app.payroll.routers.salary import salary_bp
    from app.payroll.routers.payroll_engine import payroll_engine_bp
    from app.payroll.routers.statutory import statutory_bp
    from app.payroll.routers.payslips import payslips_bp
    from app.payroll.routers.fnf import fnf_bp
    from app.payroll.routers.reports import reports_bp
    from app.ess.routers.ess import ess_bp
    from app.workflow.routers.workflow import workflow_bp, notifications_bp

    for mod in (
        "app.payroll.routers.hr_payroll",
        "app.taxation.routers.hr_taxation",
        "app.taxation.routers.employee_taxation",
        "app.ess.routers.employee_profile",
        "app.payroll.routers.employee_payroll",
    ):
        import_module(mod)

    routers = [
        pages_router,
        employee_bp.router,
        hr_bp.router,
        form16_processing_bp.router,
        contract_bp.router,
        salary_bp.router,
        payroll_engine_bp.router,
        statutory_bp.router,
        payslips_bp.router,
        fnf_bp.router,
        reports_bp.router,
        ess_bp.router,
        workflow_bp.router,
        notifications_bp.router,
    ]
    for r in routers:
        app.include_router(r)


_register_routers()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=DEBUG)
