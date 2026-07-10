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
from typing import Any

from fastapi import Body, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
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

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

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
    id_migration = db.init_db()
    if id_migration:
        print(f"AIQ: renumbered legacy employee ids to numeric ids: {id_migration}")


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


def _rules_with_overrides() -> list[dict[str, Any]]:
    """Return rule metadata plus admin enable/severity overrides."""
    overrides = db.get_rule_overrides()
    out: list[dict[str, Any]] = []
    for rule in all_rules():
        ov = overrides.get(rule["id"], {})
        rule["default_severity"] = rule.get("severity")
        rule["enabled"] = ov.get("enabled", rule.get("default_enabled", True))
        if ov.get("severity"):
            rule["severity"] = ov["severity"]
        rule["effective_severity"] = rule.get("severity")
        out.append(rule)
    return out


def _infer_plan_context(detail_or_employee: dict[str, Any]) -> dict[str, Any]:
    """Infer only provider/tool family from model names; paid plan still needs confirmation."""
    model_usage = detail_or_employee.get("model_usage") or {}
    models = " ".join(str(m).lower() for m in model_usage.keys())
    provider = "unknown"
    if "claude" in models or "opus" in models or "sonnet" in models or "haiku" in models:
        provider = "claude"
    elif "gpt" in models or "codex" in models or "openai" in models:
        provider = "codex"
    elif "copilot" in models:
        provider = "copilot"
    elif "opencode" in models:
        provider = "opencode"
    return {
        "provider": provider,
        "source": "inferred_from_model_usage" if provider != "unknown" else "not_inferred",
        "confidence": "tool-family-only" if provider != "unknown" else "none",
        "requires_confirmation": True,
        "note": "Agent harness logs can identify provider/tool family, but not the paid enterprise plan, seat tier, or rolling-window allowance. Configure that in AIQ admin or collector.",
    }


def _apply_rule_policy(anti_patterns: list[dict[str, Any]], plan_context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Apply admin rule overrides, privacy policy, and rolling-window severity policy."""
    rules_by_id = {r["id"]: r for r in _rules_with_overrides()}
    pc = plan_context or {}
    billing = str(pc.get("billing_mode") or pc.get("plan_type") or "").lower()
    plan_id = str(pc.get("plan_id") or pc.get("plan_type") or "").lower()
    is_rolling = "rolling" in billing or plan_id.startswith(("claude_", "codex_"))
    out: list[dict[str, Any]] = []
    for raw in anti_patterns:
        ap = dict(raw)
        ap.pop("examples", None)  # never expose raw prompt examples in dashboard APIs
        rule = rules_by_id.get(ap.get("rule_id"))
        if rule:
            if not rule.get("enabled", True):
                continue
            ap.setdefault("rule_name", rule.get("name"))
            ap.setdefault("rule_group", rule.get("group"))
            ap["description"] = rule.get("description", "")
            ap["suggestion"] = rule.get("suggestion", "")
            ap["severity"] = rule.get("effective_severity") or ap.get("severity")
        if ap.get("rule_id") == "model-overreliance" and is_rolling:
            ap["severity"] = "low"
            ap["description"] = "Single-model usage on a rolling-window seat is usually a routing/coaching signal, not a high-risk cost issue."
            ap["suggestion"] = "Treat as low-priority unless it coincides with premium waste, poor scores, or high quota pressure."
        out.append(ap)
    return out


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

    employee_id is always a mothership-assigned numeric id, unless the caller
    already supplies a numeric one (e.g. a future SSO/Azure AD integration
    passing its own numeric object id) — human-readable slugs are ignored so
    the id keeps meaning once real identity providers are wired in.
    """
    requested = (req.employee_id or "").strip()
    employee_id = requested if requested.isdigit() else db.next_numeric_employee_id()
    result = db.register_employee_from_invite(
        req.invite_code,
        employee_id=employee_id,
        name=req.name,
        email=req.email,
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


@app.get("/api/org/directory")
def org_directory() -> dict[str, Any]:
    """Editable org directory for mothership: employees, teams, clients, projects."""
    return {
        "employees": db.list_employees(),
        "teams": db.list_teams(),
        "clients": db.list_clients(),
        "projects": db.get_all_projects(),
    }


@app.put("/api/employees/{employee_id}")
def update_employee(
    employee_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, Any]:
    _require_admin(x_admin_key)
    ok = db.update_employee_profile(
        employee_id,
        name=body.get("name"),
        email=body.get("email"),
        team=body.get("team"),
    )
    if not ok:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found")
    return {"status": "ok", "employee_id": employee_id}


@app.delete("/api/employees/{employee_id}")
def remove_employee(
    employee_id: str,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, Any]:
    _require_admin(x_admin_key)
    ok = db.delete_employee(employee_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found")
    return {"status": "ok", "employee_id": employee_id}


@app.put("/api/teams/{team_name}")
def upsert_team(
    team_name: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, Any]:
    _require_admin(x_admin_key)
    return {"status": "ok", "team": db.upsert_team(team_name, body.get("description"))}


@app.delete("/api/teams/{team_name}")
def delete_team(
    team_name: str,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, Any]:
    _require_admin(x_admin_key)
    db.delete_team(team_name)
    return {"status": "ok", "team": team_name}


@app.put("/api/clients/{client_name}")
def upsert_client(
    client_name: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, Any]:
    _require_admin(x_admin_key)
    return {"status": "ok", "client": db.upsert_client(client_name, body.get("description"))}


@app.delete("/api/clients/{client_name}")
def delete_client(
    client_name: str,
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, Any]:
    _require_admin(x_admin_key)
    db.delete_client(client_name)
    return {"status": "ok", "client": client_name}


def _employee_detail_payload(employee_id: str) -> dict[str, Any] | None:
    """Build full employee detail and enrich anti-patterns with rule metadata."""
    detail = db.get_employee_detail(employee_id)
    if detail is None:
        return None
    inferred_plan = _infer_plan_context(detail)
    stored_plan = detail.get("plan_context") or {}
    override_plan = db.get_plan_override(employee_id) or {}
    plan_context = {**inferred_plan, **stored_plan, **override_plan}
    detail["plan_context"] = plan_context
    detail["plan_inference"] = inferred_plan
    detail["plan_config_source"] = "admin_override" if override_plan else ("collector" if stored_plan else "inferred_provider_only")
    detail["anti_patterns"] = _apply_rule_policy(detail.get("anti_patterns", []), plan_context)

    # Add the employee's project membership so /me can explain where their AI work went.
    employee_projects = []
    for p in db.get_all_projects():
        for pe in p.get("employees") or []:
            if pe.get("employee_id") == employee_id:
                employee_projects.append({
                    "project_id": p.get("project_id"),
                    "project_name": p.get("project_name"),
                    "team": p.get("team") or pe.get("team"),
                    "client": p.get("client"),
                    "customer_name": p.get("customer_name"),
                    "git_remote_url": p.get("git_remote_url"),
                    "harness_usage": p.get("harness_usage") or {},
                    "billing_code": p.get("billing_code"),
                    "sessions": pe.get("sessions") or 0,
                    "requests": pe.get("requests") or 0,
                    "ai_loc": pe.get("ai_loc") or 0,
                    "cost_usd": pe.get("cost_usd") or 0,
                    "active_days": pe.get("active_days") or 0,
                    "detected_project_id": pe.get("detected_project_id"),
                    "detected_project_name": pe.get("detected_project_name"),
                    "detected_project_path": pe.get("detected_project_path"),
                    "project_total_cost_usd": p.get("total_cost_usd") or 0,
                    "project_people": len(p.get("employees") or []),
                    "harness_usage": p.get("harness_usage") or {},
                })
    employee_projects.sort(key=lambda p: p["cost_usd"], reverse=True)
    detail["projects"] = employee_projects

    # Add cost-engine interpretation and specific plan-fit recommendation.
    try:
        from cost_engine import analyze_plan_fit, interpret_cost

        scores = detail.get("practice_scores") or {}
        vals = []
        for key in ["prompt-quality", "session-hygiene", "code-review", "tool-mastery", "context-management"]:
            v = scores.get(key)
            if isinstance(v, dict):
                raw_score = v.get("score", 0) or 0
            else:
                raw_score = v or 0
            vals.append(float(raw_score))
        overall = sum(vals) / len(vals) if vals else 0.0
        summary = dict(detail.get("summary") or {})
        summary.setdefault("period_start", detail.get("period_start"))
        summary.setdefault("period_end", detail.get("period_end"))
        plan_context = detail.get("plan_context") or {}
        detail["summary"] = summary
        detail["cost_interpretation"] = interpret_cost(summary, plan_context)
        detail["plan_fit"] = analyze_plan_fit(summary, plan_context, overall)
        from recommendations import recommendations_for_employee
        detail["recommendations"] = recommendations_for_employee({
            "summary": summary,
            "practice_scores": detail.get("practice_scores") or {},
            "anti_patterns": detail.get("anti_patterns") or [],
            "plan_context": plan_context,
            "overall_score": overall,
        })
    except Exception:
        # Keep employee detail resilient even if the catalog/cost engine is unavailable.
        detail["cost_interpretation"] = {}
        detail["plan_fit"] = {}
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
    for e in employees:
        # List view does not include full model_usage, so inference happens in detail;
        # still apply disabled/severity policy to visible flags.
        plan_override = db.get_plan_override(e.get("employee_id") or "") or {}
        e["plan_context"] = plan_override
        e["plan_config_source"] = "admin_override" if plan_override else "not_configured_in_mothership"
        e["anti_patterns"] = _apply_rule_policy(e.get("anti_patterns") or [], plan_override)
        e["high_severity_count"] = sum(1 for ap in e["anti_patterns"] if ap.get("severity") == "high" and ap.get("triggered"))
        e["anti_patterns_count"] = len(e["anti_patterns"])
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
    detail["assignable_projects"] = db.list_manual_projects()
    return detail


@app.put("/api/me/projects/{detected_project_id}")
def assign_my_project(
    detected_project_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> dict[str, Any]:
    """Assign one detected folder/project to an admin project; empty means Other Usage."""
    employee_id = _require_api_key(x_api_key)
    try:
        db.set_project_assignment(employee_id, detected_project_id, body.get("project_id") or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok"}


@app.get("/api/me/history")
def my_history(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> list[dict[str, Any]]:
    """Score history over time for the API key owner only (personal Activity tab)."""
    employee_id = _require_api_key(x_api_key)
    return db.get_employee_history(employee_id)


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
    """Rule metadata plus admin enable/severity overrides."""
    return _rules_with_overrides()


@app.put("/api/rules/{rule_id}")
def update_rule(
    rule_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, Any]:
    """Enable/disable a rule or override its severity from the admin dashboard."""
    _require_admin(x_admin_key)
    known = {r["id"] for r in all_rules()}
    if rule_id not in known:
        raise HTTPException(status_code=404, detail=f"Unknown rule '{rule_id}'")
    try:
        override = db.set_rule_override(
            rule_id,
            enabled=body.get("enabled") if "enabled" in body else None,
            severity=body.get("severity") if "severity" in body else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", **override}


@app.get("/api/employees/{employee_id}/plan")
def employee_plan(employee_id: str) -> dict[str, Any]:
    """Return plan context from admin override or latest collector payload plus inference note."""
    detail = _employee_detail_payload(employee_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found")
    return {
        "employee_id": employee_id,
        "plan_context": detail.get("plan_context") or {},
        "plan_inference": detail.get("plan_inference") or {},
        "source": detail.get("plan_config_source") or "unknown",
    }


@app.put("/api/employees/{employee_id}/plan")
def update_employee_plan(
    employee_id: str,
    body: dict[str, Any] = Body(default_factory=dict),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> dict[str, Any]:
    """Set admin-confirmed plan context for an employee."""
    _require_admin(x_admin_key)
    allowed = {
        "provider", "plan_id", "plan_type", "plan_name", "billing_mode",
        "seat_cost_usd", "rolling_window_usd", "rolling_window_days",
        "rolling_window_hours", "included_credits", "api_cost_buffer",
        "context_window_tokens", "max_context_tokens",
    }
    plan_context = {k: v for k, v in body.items() if k in allowed and v not in ("", None)}
    if not plan_context:
        raise HTTPException(status_code=400, detail="No plan fields supplied")
    try:
        saved = db.set_plan_override(employee_id, plan_context)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"Employee '{employee_id}' not found") from exc
    return {"status": "ok", "employee_id": employee_id, "plan_context": saved}


# ---------------------------------------------------------------------------

# Org / Executive / Investor views
# ---------------------------------------------------------------------------


def _org_rollup() -> dict[str, Any]:
    employees = db.list_employees()
    projects = db.get_all_projects()
    total_cost = sum(float(p.get("total_cost_usd") or 0) for p in projects)
    total_requests = sum(int(p.get("total_requests") or 0) for p in projects)
    total_ai_loc = sum(int(p.get("total_ai_loc") or 0) for p in projects)
    total_user_loc = sum(int(p.get("total_user_loc") or 0) for p in projects)
    active_people = len(employees)
    active_projects = len(projects)

    # Team and client rollups from projects; employee score rollups from employees.
    by_team: dict[str, dict[str, Any]] = {}
    for p in projects:
        team = p.get("team") or (p.get("employees") or [{}])[0].get("team") or "Unassigned"
        bucket = by_team.setdefault(team, {"projects": 0, "employees": set(), "cost_usd": 0.0, "requests": 0, "ai_loc": 0})
        bucket["projects"] += 1
        bucket["cost_usd"] += float(p.get("total_cost_usd") or 0)
        bucket["requests"] += int(p.get("total_requests") or 0)
        bucket["ai_loc"] += int(p.get("total_ai_loc") or 0)
        for e in p.get("employees") or []:
            if e.get("employee_id"):
                bucket["employees"].add(e["employee_id"])

    team_rows = []
    for team, info in by_team.items():
        team_rows.append({
            "team": team,
            "projects": info["projects"],
            "employees": len(info["employees"]),
            "cost_usd": round(info["cost_usd"], 2),
            "requests": info["requests"],
            "ai_loc": info["ai_loc"],
            "cost_per_request": round(info["cost_usd"] / info["requests"], 4) if info["requests"] else 0,
        })
    team_rows.sort(key=lambda x: x["cost_usd"], reverse=True)

    high_value = []
    attention = []
    for p in projects:
        requests = int(p.get("total_requests") or 0)
        cost = float(p.get("total_cost_usd") or 0)
        ai_loc = int(p.get("total_ai_loc") or 0)
        people = len(p.get("employees") or [])
        item = {
            "project_id": p.get("project_id"),
            "project_name": p.get("project_name"),
            "team": p.get("team") or (p.get("employees") or [{}])[0].get("team") or "Unassigned",
            "cost_usd": round(cost, 2),
            "requests": requests,
            "ai_loc": ai_loc,
            "employees": people,
            "active_days": p.get("active_days") or 0,
            "cost_per_request": round(cost / requests, 4) if requests else 0,
            "ai_loc_per_dollar": round(ai_loc / cost, 2) if cost else 0,
        }
        if ai_loc and cost:
            high_value.append(item)
        if cost >= 20 or people >= 3 or (requests and cost / requests > 1):
            attention.append(item)
    high_value.sort(key=lambda x: x["ai_loc_per_dollar"], reverse=True)
    attention.sort(key=lambda x: x["cost_usd"], reverse=True)

    return {
        "totals": {
            "employees": active_people,
            "projects": active_projects,
            "requests": total_requests,
            "ai_loc": total_ai_loc,
            "user_loc": total_user_loc,
            "cost_usd": round(total_cost, 2),
            "avg_cost_per_project": round(total_cost / active_projects, 2) if active_projects else 0,
            "cost_per_request": round(total_cost / total_requests, 4) if total_requests else 0,
            "ai_loc_per_dollar": round(total_ai_loc / total_cost, 2) if total_cost else 0,
        },
        "team_rollup": team_rows,
        "top_projects_by_spend": projects[:10],
        "high_value_projects": high_value[:10],
        "needs_attention": attention[:10],
    }


def _masked_project(p: dict[str, Any], idx: int, reveal_financials: bool) -> dict[str, Any]:
    cost = round(float(p.get("total_cost_usd") or p.get("cost_usd") or 0), 2)
    requests = int(p.get("total_requests") or p.get("requests") or 0)
    ai_loc = int(p.get("total_ai_loc") or p.get("ai_loc") or 0)
    employees = p.get("employees")
    people = len(employees) if isinstance(employees, list) else int(employees or 0)
    return {
        "project_label": f"Project {idx:02d}",
        "team_label": p.get("team_label") or p.get("team") or (employees or [{}])[0].get("team") if isinstance(employees, list) and employees else p.get("team") or "Unassigned",
        "people": people,
        "active_days": p.get("active_days") or 0,
        "requests": requests,
        "ai_loc": ai_loc,
        "cost_usd": cost if reveal_financials else None,
        "cost_band": _cost_band(cost),
        "work_mix": p.get("work_types") or {},
        "model_mix": p.get("model_usage") or {},
        "ai_loc_per_dollar": round(ai_loc / cost, 2) if reveal_financials and cost else None,
    }


def _cost_band(cost: float) -> str:
    if cost >= 100:
        return "$100+"
    if cost >= 50:
        return "$50-$99"
    if cost >= 20:
        return "$20-$49"
    if cost > 0:
        return "$1-$19"
    return "$0"


@app.get("/api/org/overview")
def org_overview() -> dict[str, Any]:
    """Executive org overview: where AI spend is going and whether it is productive."""
    return _org_rollup()


@app.get("/api/org/investor-view")
def investor_view(reveal_financials: bool = Query(True, description="Include exact spend; when false only cost bands are returned")) -> dict[str, Any]:
    """Masked view suitable for investors/clients: preserves rollups, hides people/work/client details."""
    rollup = _org_rollup()
    projects = db.get_all_projects()
    return {
        "summary": rollup["totals"],
        "masking": {
            "employees": "Names hidden; only counts are shown",
            "projects": "Project names/paths hidden; stable labels are used",
            "clients": "Client names and billing codes hidden",
            "work": "Only high-level work/mode distributions are shown",
            "financials": "Exact spend shown" if reveal_financials else "Exact spend hidden; cost bands shown",
        },
        "projects": [_masked_project(p, i + 1, reveal_financials) for i, p in enumerate(projects)],
        "team_rollup": rollup["team_rollup"],
        "high_value_projects": [_masked_project(p, i + 1, reveal_financials) for i, p in enumerate(rollup["high_value_projects"])],
    }


@app.get("/api/org/export/projects.csv")
def export_projects_csv(masked: bool = Query(False, description="Mask project/client/path fields")) -> Response:
    """CSV export for finance/client reporting."""
    import csv
    import io

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow([
        "project_id", "project_name", "team", "client", "billing_code", "employees", "sessions",
        "requests", "ai_loc", "user_loc", "input_tokens", "output_tokens", "cost_usd",
        "active_days", "first_activity", "last_activity", "files_edited_count",
    ])
    for idx, p in enumerate(db.get_all_projects(), start=1):
        writer.writerow([
            f"project-{idx:02d}" if masked else p.get("project_id"),
            f"Project {idx:02d}" if masked else p.get("project_name"),
            p.get("team") or (p.get("employees") or [{}])[0].get("team") or "Unassigned",
            "MASKED" if masked and p.get("client") else (p.get("client") or ""),
            "MASKED" if masked and p.get("billing_code") else (p.get("billing_code") or ""),
            len(p.get("employees") or []),
            p.get("total_sessions") or 0,
            p.get("total_requests") or 0,
            p.get("total_ai_loc") or 0,
            p.get("total_user_loc") or 0,
            p.get("total_input_tokens") or 0,
            p.get("total_output_tokens") or 0,
            round(float(p.get("total_cost_usd") or 0), 2),
            p.get("active_days") or 0,
            p.get("first_activity") or "",
            p.get("last_activity") or "",
            p.get("files_edited_count") or 0,
        ])
    return Response(
        out.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=aiq-projects.csv"},
    )


@app.get("/api/org/staffing")
def staffing_intelligence() -> dict[str, Any]:
    """Staffing/capacity recommendations derived from latest employee + project data."""
    employees = db.list_employees()
    projects = db.get_all_projects()
    project_count_by_employee: dict[str, int] = {}
    for p in projects:
        for pe in p.get("employees") or []:
            eid = pe.get("employee_id")
            if not eid:
                continue
            project_count_by_employee[eid] = project_count_by_employee.get(eid, 0) + 1

    high_capacity: list[dict[str, Any]] = []
    train_before_more_load: list[dict[str, Any]] = []
    underutilized: list[dict[str, Any]] = []
    overloaded: list[dict[str, Any]] = []

    for e in employees:
        m = e.get("metrics") or {}
        score = float(m.get("overall_score") or 0)
        requests = int(m.get("total_requests") or 0)
        cost = float(m.get("display_cost_usd", m.get("estimated_cost_usd", 0)) or 0)
        eid = str(e.get("employee_id") or "")
        projects_n = project_count_by_employee.get(eid, int(m.get("total_workspaces") or 0))
        high_flags = int(e.get("high_severity_count") or 0)
        anti_count = int(e.get("anti_patterns_count") or 0)
        row = {
            "employee_id": e.get("employee_id"),
            "name": e.get("name") or e.get("employee_id"),
            "team": e.get("team") or "Unassigned",
            "overall_score": round(score, 1),
            "requests": requests,
            "projects": projects_n,
            "cost_usd": round(cost, 2),
            "anti_patterns": anti_count,
            "high_severity": high_flags,
        }
        if score >= 80 and requests >= 25 and anti_count <= 1:
            high_capacity.append({**row, "recommendation": "Can handle more complex projects or mentor others"})
        if score < 60 or high_flags > 0 or anti_count >= 3:
            train_before_more_load.append({**row, "recommendation": "Training before adding complexity or increasing plan tier"})
        if requests < 20 and cost < 10 and score >= 60:
            underutilized.append({**row, "recommendation": "Potential relocation / more allocation available"})
        if projects_n >= 3 or (requests >= 80 and score >= 70):
            overloaded.append({**row, "recommendation": "Watch capacity; consider backup staffing or plan upgrade"})

    project_staffing = []
    for p in projects:
        people = len(p.get("employees") or [])
        requests = int(p.get("total_requests") or 0)
        cost = float(p.get("total_cost_usd") or 0)
        active_days = int(p.get("active_days") or 0)
        pressure = "normal"
        rec = "Current staffing looks acceptable"
        if requests >= 50 and people <= 1:
            pressure = "understaffed"
            rec = "High AI activity with one contributor; add backup or second owner"
        elif people >= 3 and requests < 30:
            pressure = "overstaffed"
            rec = "Several contributors but low activity; consider consolidation"
        elif cost >= 50 and people <= 2:
            pressure = "financial_watch"
            rec = "Spend concentration is high; review scope and plan fit"
        project_staffing.append({
            "project_id": p.get("project_id"),
            "project_name": p.get("project_name"),
            "team": p.get("team") or (p.get("employees") or [{}])[0].get("team") or "Unassigned",
            "people": people,
            "requests": requests,
            "cost_usd": round(cost, 2),
            "active_days": active_days,
            "pressure": pressure,
            "recommendation": rec,
        })
    project_staffing.sort(key=lambda x: (x["pressure"] == "normal", -x["cost_usd"]))

    return {
        "summary": {
            "high_capacity": len(high_capacity),
            "train_before_more_load": len(train_before_more_load),
            "underutilized": len(underutilized),
            "overloaded": len(overloaded),
            "projects_flagged": sum(1 for p in project_staffing if p["pressure"] != "normal"),
        },
        "high_capacity": sorted(high_capacity, key=lambda x: x["overall_score"], reverse=True),
        "train_before_more_load": sorted(train_before_more_load, key=lambda x: (x["high_severity"], x["anti_patterns"], -x["overall_score"]), reverse=True),
        "underutilized": sorted(underutilized, key=lambda x: x["requests"]),
        "overloaded": sorted(overloaded, key=lambda x: (x["projects"], x["requests"]), reverse=True),
        "project_staffing": project_staffing,
    }


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


@app.get("/api/projects")
def projects_list() -> list[dict[str, Any]]:
    """List all projects with cross-employee aggregated stats."""
    return db.get_all_projects()


@app.post("/api/projects")
def create_project(body: dict[str, Any] = Body(...), x_admin_key: str | None = Header(default=None, alias="X-Admin-Key")):
    """Create an admin-defined project employees can assign usage to."""
    _require_admin(x_admin_key)
    try:
        return db.create_project(
            body.get("project_id") or body.get("project_name") or body.get("name"),
            body.get("project_name") or body.get("name"),
            body.get("team"), body.get("client") or body.get("customer_name"), body.get("billing_code"),
            git_remote_url=body.get("git_remote_url") or body.get("remote_url"),
            customer_name=body.get("customer_name") or body.get("client"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/projects/{project_id:path}")
def project_detail(project_id: str) -> dict[str, Any]:
    """Detail for one project with per-employee breakdown."""
    detail = db.get_project_detail(project_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Project not found")
    return detail


@app.patch("/api/projects/{project_id:path}")
def update_project(project_id: str, body: dict[str, Any] = Body(...)):
    """Admin-update project metadata (name, team, client, billing_code)."""
    ok = db.update_project_metadata(
        project_id,
        project_name=body.get("project_name"),
        team=body.get("team"),
        client=body.get("client"),
        billing_code=body.get("billing_code"),
        git_remote_url=body.get("git_remote_url") or body.get("remote_url"),
        customer_name=body.get("customer_name") or body.get("client"),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "ok", "project_id": project_id}


# ---------------------------------------------------------------------------
# Plan catalog
# ---------------------------------------------------------------------------


@app.get("/api/plans")
def plans_catalog() -> dict[str, Any]:
    """Return the full plan catalog for frontend dropdowns."""
    try:
        from plan_catalog import PLAN_CATALOG, get_all_providers, BILLING_MODE_DESCRIPTIONS
        return {
            "providers": get_all_providers(),
            "billing_modes": BILLING_MODE_DESCRIPTIONS,
            "plans": PLAN_CATALOG,
        }
    except ImportError:
        return {"providers": [], "billing_modes": {}, "plans": []}


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
