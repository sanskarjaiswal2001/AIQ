"""FastAPI application for the AIECO dashboard backend.

Exposes:
  POST /api/ingest                    - receive a collector snapshot
  GET  /api/employees                 - list employees + latest summary
  GET  /api/employees/{employee_id}   - full employee detail
  GET  /api/employees/{employee_id}/history - score history
  GET  /api/team/overview             - team-wide aggregates
  GET  /api/rules                     - static anti-pattern rule metadata
  GET  /api/health                    - health check

The dashboard frontend (static HTML/JS/CSS) is served from
``/data/aieco-dashboard/dashboard/`` at the root path ``/`` via StaticFiles.
"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import database as db
from models import (
    HealthResponse,
    IngestRequest,
    IngestResponse,
    InviteCreateRequest,
    InviteCreateResponse,
    RegisterRequest,
    RegisterResponse,
)
from rules_meta import all_rules

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AIECO Dashboard API",
    description="AI engineering efficiency dashboard backend.",
    version="0.1.0",
)

# CORS open for all origins (internal tool).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    """Initialise the database schema on startup."""
    db.init_db()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------


def _admin_key() -> str:
    return os.environ.get("AIQ_ADMIN_KEY", "").strip()


def _auth_enabled() -> bool:
    return bool(_admin_key())


def _require_admin(x_admin_key: str | None) -> None:
    key = _admin_key()
    if key and x_admin_key != key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key")


def _api_employee(x_api_key: str | None) -> str | None:
    return db.verify_api_key(x_api_key or "") if x_api_key else None


def _require_api_key(x_api_key: str | None) -> str:
    employee_id = _api_employee(x_api_key)
    if not employee_id:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")
    return employee_id


def _slugify_employee_id(name: str | None) -> str:
    base = (name or "employee").strip().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base or "employee"


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Health check: DB path + employee count."""
    return HealthResponse(
        status="ok",
        db_path=os.path.abspath(db.get_db_path()),
        employee_count=db.count_employees(),
    )


@app.post("/api/ingest", response_model=IngestResponse)
def ingest(req: IngestRequest, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> IngestResponse:
    """Receive a metrics snapshot from a collector.

    When AIQ_ADMIN_KEY is configured, collectors must send a valid X-API-Key
    issued through /api/register. The key is bound to one employee_id.
    """
    if _auth_enabled():
        authed_employee = _require_api_key(x_api_key)
        if authed_employee != req.employee_id:
            raise HTTPException(status_code=403, detail="API key is not valid for this employee_id")
    payload = req.model_dump()
    try:
        snapshot_id = db.ingest_snapshot(payload)
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Ingest failed: {exc}") from exc
    return IngestResponse(status="ok", snapshot_id=snapshot_id)


@app.post("/api/register", response_model=RegisterResponse)
def register(req: RegisterRequest) -> RegisterResponse:
    """Register an employee collector with an invite code.

    Returns a one-time-visible API key. The collector stores it in ~/.aiq/config.toml
    and sends it as X-API-Key on future /api/ingest calls.
    """
    employee_id = req.employee_id or _slugify_employee_id(req.name)
    result = db.register_employee_from_invite(
        req.invite_code,
        employee_id=employee_id,
        name=req.name,
        team=req.team,
    )
    if result is None:
        raise HTTPException(status_code=400, detail="Invalid or exhausted invite code")
    return RegisterResponse(**result)


@app.post("/api/admin/invites", response_model=InviteCreateResponse)
def admin_create_invite(
    req: InviteCreateRequest,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> InviteCreateResponse:
    """Create an employee registration invite. Protected by X-Admin-Key when configured."""
    _require_admin(x_admin_key)
    if req.uses_remaining < 1:
        raise HTTPException(status_code=400, detail="uses_remaining must be >= 1")
    try:
        invite = db.create_invite(req.code, req.team, req.uses_remaining)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not create invite: {exc}") from exc
    return InviteCreateResponse(**invite)


@app.get("/api/admin/invites")
def admin_list_invites(x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")) -> list[dict[str, Any]]:
    """List registration invites. Protected by X-Admin-Key when configured."""
    _require_admin(x_admin_key)
    return db.list_invites()


def _employee_detail_payload(employee_id: str) -> dict[str, Any] | None:
    """Build full employee detail and enrich anti-patterns with rule metadata."""
    detail = db.get_employee_detail(employee_id)
    if detail is None:
        return None
    rules_by_id = {r["id"]: r for r in all_rules()}
    for ap in detail.get("anti_patterns", []):
        rule = rules_by_id.get(ap.get("rule_id"))
        if rule:
            ap.setdefault("rule_name", rule["name"])
            ap.setdefault("rule_group", rule["group"])
            ap["description"] = rule.get("description", "")
            ap["suggestion"] = rule.get("suggestion", "")
    return detail


def _sort_employees(employees: list[dict[str, Any]], sort: str, order: str) -> list[dict[str, Any]]:
    """Sort the employees list by a supported field."""
    reverse = order.lower() == "desc"

    def key(e: dict[str, Any]) -> Any:
        if sort == "overall_score":
            return e.get("metrics", {}).get("overall_score") or 0.0
        if sort == "name":
            return (e.get("name") or "").lower()
        if sort == "team":
            return (e.get("team") or "").lower()
        if sort == "total_requests":
            return e.get("metrics", {}).get("total_requests") or 0
        if sort == "estimated_cost_usd":
            return e.get("metrics", {}).get("estimated_cost_usd") or 0.0
        if sort == "latest_snapshot":
            return e.get("latest_snapshot") or ""
        # default: employee_id
        return e.get("employee_id") or ""

    return sorted(employees, key=key, reverse=reverse)


@app.get("/api/employees")
def list_employees(
    team: str | None = Query(None, description="Filter by team name"),
    sort: str = Query("employee_id", description="Sort field: overall_score|name|team|total_requests|estimated_cost_usd|latest_snapshot"),
    order: str = Query("asc", description="Sort order: asc|desc"),
) -> list[dict[str, Any]]:
    """List all employees with their latest snapshot summary."""
    employees = db.list_employees(team=team)
    return _sort_employees(employees, sort, order)


@app.get("/api/employees/{employee_id}")
def employee_detail(employee_id: str) -> dict[str, Any]:
    """Full detail for one employee (latest snapshot) + recommendations."""
    detail = _employee_detail_payload(employee_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found")
    return detail


@app.get("/api/me")
def my_detail(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> dict[str, Any]:
    """Employee self-view: full detail for the API key owner only."""
    employee_id = _require_api_key(x_api_key)
    detail = _employee_detail_payload(employee_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found")
    return detail


@app.get("/api/employees/{employee_id}/history")
def employee_history(employee_id: str) -> list[dict[str, Any]]:
    """Score history over time for an employee."""
    # Verify employee exists.
    with db.db() as conn:
        emp = db.get_employee(conn, employee_id)
    if emp is None:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found")
    return db.get_employee_history(employee_id)


@app.get("/api/team/overview")
def team_overview() -> dict[str, Any]:
    """Team-wide aggregate view."""
    return db.get_team_overview()


@app.get("/api/rules")
def rules() -> list[dict[str, Any]]:
    """Static metadata for all anti-pattern rules."""
    return all_rules()


# ---------------------------------------------------------------------------
# Static frontend serving
# ---------------------------------------------------------------------------

DASHBOARD_DIR = os.environ.get("DASHBOARD_DIR", "/data/aieco-dashboard/dashboard")


@app.get("/me")
def me_page() -> FileResponse:
    """Serve the SPA for employee self-view."""
    index = os.path.join(DASHBOARD_DIR, "index.html")
    if not os.path.isfile(index):
        raise HTTPException(status_code=404, detail="Dashboard frontend not found")
    return FileResponse(index)


def _mount_static() -> None:
    """Mount the dashboard frontend at / if the directory exists.

    Done lazily (after startup) so the server still works even if the
    dashboard directory doesn't exist yet. Falls back to a root JSON
    message when no static directory is present.
    """
    if os.path.isdir(DASHBOARD_DIR) and os.listdir(DASHBOARD_DIR):
        app.mount("/", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
    else:
        @app.get("/")
        def _root() -> dict[str, Any]:
            return {
                "name": "AIECO Dashboard API",
                "status": "running",
                "dashboard": f"not mounted (no files in {DASHBOARD_DIR})",
                "docs": "/docs",
                "endpoints": [
                    "/api/health",
                    "/api/ingest",
                    "/api/employees",
                    "/api/employees/{employee_id}",
                    "/api/employees/{employee_id}/history",
                    "/api/team/overview",
                    "/api/rules",
                ],
            }


# Mount after all /api routes are registered so they take precedence.
_mount_static()


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------


@app.exception_handler(HTTPException)
async def _http_exc_handler(_request: Any, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
