"""
FastAPI compatibility layer — Flask-like session, request, templates, and routing.

Allows existing route handler logic to remain unchanged while running on FastAPI.
"""
from __future__ import annotations

import os
from contextvars import ContextVar
from typing import Any, Callable, Dict, List, Optional, Union
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.responses import FileResponse
from starlette.templating import Jinja2Templates

from app.base.utils.config import UPLOAD_FOLDER

# ── Request context (thread-safe per-request) ─────────────────────────────

_current_request: ContextVar[Optional[Request]] = ContextVar("current_request", default=None)


def get_request() -> Request:
    req = _current_request.get()
    if req is None:
        raise RuntimeError("No active request context")
    return req


# ── Session proxy (Flask session interface) ───────────────────────────────

class _SessionProxy:
    def __getitem__(self, key: str) -> Any:
        return get_request().session[key]

    def __setitem__(self, key: str, value: Any) -> None:
        get_request().session[key] = value

    def __delitem__(self, key: str) -> None:
        del get_request().session[key]

    def __contains__(self, key: str) -> bool:
        return key in get_request().session

    def get(self, key: str, default: Any = None) -> Any:
        return get_request().session.get(key, default)

    def clear(self) -> None:
        get_request().session.clear()

    def pop(self, key: str, default: Any = None) -> Any:
        return get_request().session.pop(key, default)


session = _SessionProxy()


# ── Request proxy (Flask request interface) ───────────────────────────────

class _FormProxy:
    def __init__(self, data: dict):
        self._data = data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def items(self):
        return self._data.items()

    def __iter__(self):
        return iter(self._data)


class _ArgsProxy:
    def __init__(self, data: dict):
        self._data = data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class _FilesProxy:
    def __init__(self, files: dict):
        self._files = files

    def get(self, key: str, default: Any = None) -> Any:
        return self._files.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._files


class _RequestProxy:
    @property
    def method(self) -> str:
        return get_request().method

    @property
    def form(self) -> _FormProxy:
        req = get_request()
        form = getattr(req.state, "_form", None)
        if form is None:
            return _FormProxy({})
        return _FormProxy(form)

    @property
    def args(self) -> _ArgsProxy:
        return _ArgsProxy(dict(get_request().query_params))

    @property
    def files(self) -> _FilesProxy:
        return _FilesProxy(getattr(get_request().state, "_files", {}))


request = _RequestProxy()


# ── Flash messages (Flask-compatible, stored in session) ──────────────────

def flash(message: str, category: str = "info") -> None:
    flashes = session.get("_flashes", [])
    if flashes is None:
        flashes = []
    flashes.append((category, message))
    session["_flashes"] = flashes


def get_flashed_messages(with_categories: bool = False) -> list:
    flashes = session.pop("_flashes", []) or []
    if with_categories:
        return flashes
    return [m for _, m in flashes]


# ── Redirect exception (auth decorators) ─────────────────────────────────

class RedirectException(Exception):
    def __init__(self, url: str, status_code: int = 303):
        self.url = url
        self.status_code = status_code


# ── Templates ───────────────────────────────────────────────────────────

_APP_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEMPLATE_DIRS = [
    os.path.join(_APP_DIR, "base", "templates"),
    os.path.join(_APP_DIR, "payroll", "templates"),
    os.path.join(_APP_DIR, "taxation", "templates"),
    os.path.join(_APP_DIR, "ess", "templates"),
    os.path.join(_APP_DIR, "workflow", "templates"),
]

templates = Jinja2Templates(directory=TEMPLATE_DIRS[0])
templates.env.loader.searchpath = TEMPLATE_DIRS


def _url_for(endpoint: str, **values) -> str:
    """Flask-compatible url_for: blueprint.endpoint → FastAPI route name."""
    if endpoint == "static":
        filename = values.pop("filename", "")
        return f"/static/{filename}"
    route_name = endpoint.replace(".", "__")
    req = get_request()
    try:
        return str(req.url_for(route_name, **values))
    except Exception:
        pass
    # Fallback: build from known patterns (path params)
    return _fallback_url_for(endpoint, **values)


def _fallback_url_for(endpoint: str, **values) -> str:
    """Manual URL builder when route not yet registered."""
    _PATHS = {
        "auth.login": "/auth/login",
        "auth.logout": "/auth/logout",
        "auth.switch_role": "/auth/switch-role",
        "dashboard": "/dashboard",
        "index": "/",
        "serve_upload": "/uploads/{employee_id}/{filename}",
    }
    path = _PATHS.get(endpoint, f"/{endpoint.replace('.', '/')}")
    for key, val in values.items():
        path = path.replace(f"{{{key}}}", str(val))
    return path


def _template_context(**kwargs) -> dict:
    req = get_request()
    ctx = {
        "request": req,
        "session": req.session,
        "url_for": _url_for,
        "get_flashed_messages": get_flashed_messages,
    }
    # Notification badge (replaces Flask context processor)
    user = session.get("user")
    if user:
        try:
            from app.workflow.services.notification_service import get_unread_count
            count = get_unread_count(user["employee_id"])
            if user.get("role") == "hr":
                count += get_unread_count("hr")
            ctx["unread_notifications_count"] = count
        except Exception:
            ctx["unread_notifications_count"] = 0
    else:
        ctx["unread_notifications_count"] = 0
    ctx.update(kwargs)
    return ctx


def render_template(template_name: str, **context) -> str:
    """Render Jinja2 template to HTML string (Flask-compatible)."""
    ctx = _template_context(**context)
    return templates.env.get_template(template_name).render(ctx)


def redirect(location: str, code: int = 302) -> RedirectException:
    return RedirectException(location, status_code=code)


def url_for(endpoint: str, **values) -> str:
    return _url_for(endpoint, **values)


def abort(code: int = 404) -> None:
    from fastapi import HTTPException
    raise HTTPException(status_code=code)


def jsonify(data: Any) -> JSONResponse:
    return JSONResponse(content=data)


def make_response(data: Any) -> JSONResponse:
    """Flask make_response wrapper; supports .headers assignment on JSONResponse."""
    if isinstance(data, JSONResponse):
        return data
    if isinstance(data, (dict, list)):
        return JSONResponse(content=data)
    return JSONResponse(content=data)


# ── Response normalization ────────────────────────────────────────────────

def _normalize_response(result: Any) -> Response:
    if isinstance(result, Response):
        return result
    if isinstance(result, RedirectException):
        return RedirectResponse(url=result.url, status_code=result.status_code)
    if isinstance(result, tuple) and len(result) == 2:
        body, status = result
        if isinstance(body, Response):
            body.status_code = status
            return body
        if isinstance(body, str):
            return HTMLResponse(content=body, status_code=status)
        if isinstance(body, (dict, list)):
            return JSONResponse(content=body, status_code=status)
        return Response(content=body, status_code=status)
    if isinstance(result, str):
        return HTMLResponse(content=result)
    if isinstance(result, (dict, list)):
        return JSONResponse(content=result)
    return result


async def _parse_request_body(req: Request) -> None:
    """Cache form data and files on request.state for sync access in handlers."""
    if req.method in ("POST", "PUT", "PATCH", "DELETE"):
        content_type = req.headers.get("content-type", "")
        if "multipart/form-data" in content_type or "application/x-www-form-urlencoded" in content_type:
            form = await req.form()
            req.state._form = {k: form.get(k) for k in form.keys()}
            req.state._files = {k: form.get(k) for k in form.keys() if hasattr(form.get(k), "filename")}
        else:
            req.state._form = {}
            req.state._files = {}
    else:
        req.state._form = {}
        req.state._files = {}


# ── CompatRouter: Flask Blueprint → FastAPI APIRouter ───────────────────

class CompatRouter:
  """Drop-in replacement for Flask Blueprint."""

  def __init__(self, name: str, import_name: str = "", url_prefix: str = "", **kwargs):
      self.name = name
      self.url_prefix = url_prefix.rstrip("/") if url_prefix else ""
      self.router = APIRouter(prefix=self.url_prefix, tags=[name])
      self._before_request_hooks: List[Callable] = []
      self._after_request_hooks: List[Callable] = []

  def route(self, rule: str, methods: Optional[List[str]] = None, **options):
      methods = methods or ["GET"]

      def decorator(f: Callable):
          endpoint_name = options.get("endpoint", f.__name__)
          if options.get("endpoint") is not None:
              route_name = endpoint_name.replace(".", "__")
          else:
              route_name = f"{self.name}__{endpoint_name}"

          async def endpoint_handler(request: Request):
              token = _current_request.set(request)
              await _parse_request_body(request)
              try:
                  for hook in self._before_request_hooks:
                      result = hook()
                      if result is not None:
                          return _normalize_response(result)

                  try:
                      result = f()
                  except RedirectException as exc:
                      return RedirectResponse(url=exc.url, status_code=exc.status_code)

                  response = _normalize_response(result)

                  for hook in self._after_request_hooks:
                      hook_result = hook(response)
                      if hook_result is not None:
                          response = hook_result
                  return response
              finally:
                  _current_request.reset(token)

          path = rule if rule.startswith("/") else f"/{rule}"
          for method in methods:
              self.router.add_api_route(
                  path,
                  endpoint_handler,
                  methods=[method.upper()],
                  name=route_name,
                  include_in_schema=False,
              )
          return f
      return decorator

  def before_request(self, f: Callable):
      self._before_request_hooks.append(f)
      return f

  def after_request(self, f: Callable):
      self._after_request_hooks.append(f)
      return f

  def register_blueprint(self, *args, **kwargs):
      pass  # no-op; FastAPI uses include_router in main.py

  # Flask app_context_processor equivalent — handled in _template_context
  def app_context_processor(self, f: Callable):
      return f


# Alias for drop-in replacement
Blueprint = CompatRouter


# ── Auth decorators (unchanged interface) ─────────────────────────────────

def hr_required(f: Callable):
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            raise RedirectException(url_for("auth.login"))
        if session["user"].get("role") != "hr":
            flash("HR access required.", "danger")
            raise RedirectException(url_for("dashboard"))
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated


def employee_required(f: Callable):
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            raise RedirectException(url_for("auth.login"))
        if session["user"].get("role") not in ("employee", "hr"):
            flash("Access denied.", "danger")
            raise RedirectException(url_for("auth.login"))
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated


def login_required(f: Callable):
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            raise RedirectException(url_for("auth.login"))
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated


def manager_required(f: Callable):
    def decorated(*args, **kwargs):
        if "user" not in session:
            flash("Please log in to continue.", "warning")
            raise RedirectException(url_for("auth.login"))
        user = session["user"]
        if user.get("role") not in ["manager", "hr"]:
            flash("Access denied. Manager role required.", "danger")
            raise RedirectException(url_for("dashboard"))
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated


# ── File response helpers ─────────────────────────────────────────────────

def send_file(
    path_or_file: Any,
    mimetype: str = None,
    as_attachment: bool = False,
    download_name: str = None,
    attachment_filename: str = None,
) -> FileResponse:
    filename = download_name or attachment_filename
    if hasattr(path_or_file, "read"):
        import tempfile
        import io
        if isinstance(path_or_file, io.BytesIO):
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            tmp.write(path_or_file.getvalue())
            tmp.close()
            return FileResponse(
                tmp.name,
                media_type=mimetype or "application/octet-stream",
                filename=filename,
            )
    return FileResponse(
        path_or_file,
        media_type=mimetype or "application/octet-stream",
        filename=filename if as_attachment else None,
    )


def send_from_directory(directory: str, filename: str, as_attachment: bool = False) -> FileResponse:
    path = os.path.join(directory, filename)
    return FileResponse(
        path,
        filename=filename if as_attachment else None,
    )


# App config proxy
class _AppConfig:
    def __getitem__(self, key: str):
        if key == "UPLOAD_FOLDER":
            return UPLOAD_FOLDER
        return None

    def get(self, key: str, default=None):
        return self[key] or default


class _CurrentApp:
    config = _AppConfig()


current_app = _CurrentApp()
