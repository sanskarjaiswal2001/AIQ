"""SQLite data layer for the AIECO dashboard.

Responsibilities:
  * Open a connection to the SQLite DB (path from ``DB_PATH`` env var,
    default ``./aieco.db``) and enable WAL mode for concurrent reads.
  * Initialise the schema (employees, snapshots, metrics_summary,
    anti_patterns) on startup.
  * Provide query functions used by the API layer in ``main.py``.

All functions use ``sqlite3.Row`` so rows behave like dicts. The module is
import-safe (calling ``get_db_path`` / ``init_db`` is idempotent).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_DB_PATH = "./aieco.db"


def get_db_path() -> str:
    """Return the configured DB path (DB_PATH env var or default)."""
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------


def get_connection() -> sqlite3.Connection:
    """Create a new SQLite connection configured for this app.

    A fresh connection is created per call (FastAPI runs single-threaded by
    default with sync endpoints, and SQLite connections are cheap). WAL mode
    and foreign keys are enabled on every connection for safety.
    """
    path = get_db_path()
    # ``check_same_thread=False`` lets the connection be used across threads
    # if uvicorn is run with workers; we rely on WAL for concurrency.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA busy_timeout=5000;")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Context manager yielding a connection, committing/rolling back."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS employees (
    id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    team TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS teams (
    name TEXT PRIMARY KEY,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS clients (
    name TEXT PRIMARY KEY,
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP,
    period_start TEXT,
    period_end TEXT,
    payload_json TEXT NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);

CREATE TABLE IF NOT EXISTS metrics_summary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    snapshot_id INTEGER NOT NULL,
    period_start TEXT,
    period_end TEXT,
    total_sessions INTEGER,
    total_requests INTEGER,
    total_workspaces INTEGER,
    total_ai_loc INTEGER,
    total_input_tokens INTEGER,
    total_output_tokens INTEGER,
    estimated_cost_usd REAL,
    score_prompt_quality REAL,
    score_session_hygiene REAL,
    score_code_review REAL,
    score_tool_mastery REAL,
    score_context_management REAL,
    overall_score REAL,
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE TABLE IF NOT EXISTS anti_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    snapshot_id INTEGER NOT NULL,
    rule_id TEXT NOT NULL,
    rule_name TEXT,
    rule_group TEXT,
    severity TEXT,
    triggered INTEGER,
    occurrences INTEGER,
    total INTEGER,
    examples_json TEXT,
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_employee ON snapshots(employee_id);
CREATE INDEX IF NOT EXISTS idx_metrics_employee ON metrics_summary(employee_id);
CREATE INDEX IF NOT EXISTS idx_metrics_snapshot ON metrics_summary(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_anti_employee ON anti_patterns(employee_id);
CREATE INDEX IF NOT EXISTS idx_anti_snapshot ON anti_patterns(snapshot_id);

CREATE TABLE IF NOT EXISTS invite_codes (
    code TEXT PRIMARY KEY,
    team TEXT,
    uses_remaining INTEGER DEFAULT 1,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    expires_at TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    key_prefix TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    revoked_at TEXT,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_employee ON api_keys(employee_id);

CREATE TABLE IF NOT EXISTS projects (
    project_id TEXT PRIMARY KEY,
    project_name TEXT,
    project_path TEXT,
    team TEXT,
    client TEXT,
    billing_code TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS project_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    snapshot_id INTEGER NOT NULL,
    sessions INTEGER,
    requests INTEGER,
    ai_loc INTEGER,
    user_loc INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    estimated_cost_usd REAL,
    first_activity TEXT,
    last_activity TEXT,
    active_days INTEGER,
    model_usage_json TEXT,
    work_types_json TEXT,
    git_branches_json TEXT,
    files_edited_count INTEGER,
    FOREIGN KEY (project_id) REFERENCES projects(project_id),
    FOREIGN KEY (employee_id) REFERENCES employees(id),
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id)
);

CREATE INDEX IF NOT EXISTS idx_proj_snap_project ON project_snapshots(project_id);
CREATE INDEX IF NOT EXISTS idx_proj_snap_employee ON project_snapshots(employee_id);
CREATE INDEX IF NOT EXISTS idx_proj_snap_snapshot ON project_snapshots(snapshot_id);

CREATE TABLE IF NOT EXISTS rule_overrides (
    rule_id TEXT PRIMARY KEY,
    enabled INTEGER DEFAULT 1,
    severity TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS employee_plan_overrides (
    employee_id TEXT PRIMARY KEY,
    plan_context_json TEXT NOT NULL,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
"""


def init_db() -> None:
    """Create tables/indexes if they don't already exist."""
    with db() as conn:
        conn.executescript(SCHEMA_SQL)
        _ensure_column(conn, "employees", "email", "TEXT")


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _norm_project_name(name: str | None) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in (name or "").strip()).strip("-")


def _maybe_upsert_team(conn: sqlite3.Connection, team: str | None) -> None:
    if team:
        conn.execute("INSERT OR IGNORE INTO teams (name) VALUES (?)", (team,))


def _maybe_upsert_client(conn: sqlite3.Connection, client: str | None) -> None:
    if client:
        conn.execute("INSERT OR IGNORE INTO clients (name) VALUES (?)", (client,))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _avg(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 2) if scores else 0.0


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


# ---------------------------------------------------------------------------
# Auth / registration
# ---------------------------------------------------------------------------


def _hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def create_invite(code: str | None = None, team: str | None = None, uses_remaining: int = 1) -> dict[str, Any]:
    """Create an invite code and return it."""
    invite_code = code or "inv_" + secrets.token_urlsafe(12)
    with db() as conn:
        conn.execute(
            "INSERT INTO invite_codes (code, team, uses_remaining) VALUES (?, ?, ?)",
            (invite_code, team, uses_remaining),
        )
    return {"code": invite_code, "team": team, "uses_remaining": uses_remaining}


def list_invites() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            "SELECT code, team, uses_remaining, created_at, expires_at FROM invite_codes ORDER BY created_at DESC"
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def register_employee_from_invite(
    invite_code: str,
    *,
    employee_id: str,
    name: str | None = None,
    email: str | None = None,
    team: str | None = None,
) -> dict[str, Any] | None:
    """Consume an invite and create an employee API key.

    Returns {employee_id, api_key, key_prefix, team} or None when the invite is
    invalid/exhausted.
    """
    if not invite_code or not employee_id:
        return None
    api_key = "ak_" + secrets.token_urlsafe(32)
    key_hash = _hash_api_key(api_key)
    key_prefix = api_key[:10]
    with db() as conn:
        inv = conn.execute(
            "SELECT code, team, uses_remaining FROM invite_codes WHERE code = ?",
            (invite_code,),
        ).fetchone()
        if inv is None or int(inv["uses_remaining"] or 0) <= 0:
            return None
        effective_team = team or inv["team"]
        upsert_employee(conn, employee_id, name, effective_team, email=email)
        conn.execute(
            "UPDATE invite_codes SET uses_remaining = uses_remaining - 1 WHERE code = ?",
            (invite_code,),
        )
        conn.execute(
            "INSERT INTO api_keys (employee_id, key_hash, key_prefix) VALUES (?, ?, ?)",
            (employee_id, key_hash, key_prefix),
        )
    return {"employee_id": employee_id, "api_key": api_key, "key_prefix": key_prefix, "name": name, "email": email, "team": effective_team}


def create_employee_api_key(employee_id: str) -> dict[str, Any]:
    """Create an additional API key for an existing employee."""
    api_key = "ak_" + secrets.token_urlsafe(32)
    key_hash = _hash_api_key(api_key)
    key_prefix = api_key[:10]
    with db() as conn:
        emp = get_employee(conn, employee_id)
        if emp is None:
            upsert_employee(conn, employee_id, None, None)
        conn.execute(
            "INSERT INTO api_keys (employee_id, key_hash, key_prefix) VALUES (?, ?, ?)",
            (employee_id, key_hash, key_prefix),
        )
    return {"employee_id": employee_id, "api_key": api_key, "key_prefix": key_prefix}


def verify_api_key(api_key: str) -> str | None:
    """Return employee_id for a valid non-revoked API key, else None."""
    if not api_key:
        return None
    key_hash = _hash_api_key(api_key)
    with db() as conn:
        row = conn.execute(
            "SELECT employee_id FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
            (key_hash,),
        ).fetchone()
        return row["employee_id"] if row else None


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------


def upsert_employee(conn: sqlite3.Connection, employee_id: str, name: str | None, team: str | None, email: str | None = None) -> None:
    """Insert employee if missing, or update name/team/email when provided."""
    if name is None and team is None and email is None:
        # Ensure the employee exists even without name/team/email.
        conn.execute(
            "INSERT OR IGNORE INTO employees (id, name, email, team) VALUES (?, NULL, NULL, NULL)",
            (employee_id,),
        )
        return

    _maybe_upsert_team(conn, team)

    # Upsert: insert if missing, otherwise update non-null fields.
    conn.execute(
        """
        INSERT INTO employees (id, name, email, team)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = COALESCE(excluded.name, employees.name),
            email = COALESCE(excluded.email, employees.email),
            team = COALESCE(excluded.team, employees.team)
        """,
        (employee_id, name, email, team),
    )


def update_employee_profile(employee_id: str, *, name: str | None = None, email: str | None = None, team: str | None = None) -> bool:
    with db() as conn:
        if get_employee(conn, employee_id) is None:
            return False
        _maybe_upsert_team(conn, team)
        conn.execute(
            """
            UPDATE employees
            SET name = COALESCE(?, name), email = COALESCE(?, email), team = COALESCE(?, team)
            WHERE id = ?
            """,
            (name, email, team, employee_id),
        )
        return True


def get_employee(conn: sqlite3.Connection, employee_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_employees(team: str | None = None) -> list[dict[str, Any]]:
    """List employees with their latest snapshot summary (see GET /api/employees)."""
    with db() as conn:
        # Latest snapshot id per employee (optionally filtered by team).
        if team:
            emp_rows = conn.execute(
                "SELECT id, name, email, team, created_at FROM employees WHERE team = ? ORDER BY id",
                (team,),
            ).fetchall()
        else:
            emp_rows = conn.execute(
                "SELECT id, name, email, team, created_at FROM employees ORDER BY id"
            ).fetchall()

        results: list[dict[str, Any]] = []
        for er in emp_rows:
            eid = er["id"]
            # Latest snapshot for this employee.
            snap = conn.execute(
                "SELECT id, uploaded_at, period_start, period_end FROM snapshots "
                "WHERE employee_id = ? ORDER BY id DESC LIMIT 1",
                (eid,),
            ).fetchone()
            metrics: dict[str, Any] = {}
            ap_count = 0
            high_count = 0
            latest_snapshot = None
            period_start = None
            period_end = None
            anti_patterns: list[dict[str, Any]] = []
            if snap:
                latest_snapshot = snap["uploaded_at"]
                period_start = snap["period_start"]
                period_end = snap["period_end"]
                mrow = conn.execute(
                    "SELECT * FROM metrics_summary WHERE snapshot_id = ? LIMIT 1",
                    (snap["id"],),
                ).fetchone()
                if mrow:
                    metrics = {
                        "total_sessions": mrow["total_sessions"],
                        "total_requests": mrow["total_requests"],
                        "total_workspaces": mrow["total_workspaces"],
                        "total_ai_loc": mrow["total_ai_loc"],
                        "total_input_tokens": mrow["total_input_tokens"],
                        "total_output_tokens": mrow["total_output_tokens"],
                        "estimated_cost_usd": mrow["estimated_cost_usd"],
                        "score_prompt_quality": mrow["score_prompt_quality"],
                        "score_session_hygiene": mrow["score_session_hygiene"],
                        "score_code_review": mrow["score_code_review"],
                        "score_tool_mastery": mrow["score_tool_mastery"],
                        "score_context_management": mrow["score_context_management"],
                        "overall_score": mrow["overall_score"],
                    }
                ap_row = conn.execute(
                    "SELECT COUNT(*) AS c, "
                    "SUM(CASE WHEN severity='high' AND triggered=1 THEN 1 ELSE 0 END) AS h "
                    "FROM anti_patterns WHERE snapshot_id = ?",
                    (snap["id"],),
                ).fetchone()
                ap_count = ap_row["c"] if ap_row else 0
                high_count = ap_row["h"] if ap_row else 0
                # Fetch triggered anti-patterns for this snapshot (for training matrix)
                ap_detail_rows = conn.execute(
                    "SELECT rule_id, rule_name, rule_group, severity, triggered, occurrences, total "
                    "FROM anti_patterns WHERE snapshot_id = ? AND triggered = 1 "
                    "ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, occurrences DESC",
                    (snap["id"],),
                ).fetchall()
                anti_patterns = [
                    {
                        "rule_id": r["rule_id"],
                        "rule_name": r["rule_name"],
                        "rule_group": r["rule_group"],
                        "severity": r["severity"],
                        "triggered": bool(r["triggered"]),
                        "occurrences": r["occurrences"],
                        "total": r["total"],
                    }
                    for r in ap_detail_rows
                ]

            results.append(
                {
                    "employee_id": eid,
                    "name": er["name"],
                    "email": er["email"],
                    "team": er["team"],
                    "latest_snapshot": latest_snapshot,
                    "period_start": period_start,
                    "period_end": period_end,
                    "metrics": metrics,
                    "anti_patterns_count": ap_count,
                    "high_severity_count": high_count,
                    "anti_patterns": anti_patterns if snap else [],
                }
            )
        return results


# ---------------------------------------------------------------------------
# Snapshots / ingest
# ---------------------------------------------------------------------------


def ingest_snapshot(payload: dict[str, Any]) -> int:
    """Persist a full snapshot and its extracted rows. Returns snapshot id."""
    employee_id = payload["employee_id"]
    name = payload.get("employee_name")
    email = payload.get("employee_email") or payload.get("email")
    team = payload.get("team")
    period_start = payload.get("period_start")
    period_end = payload.get("period_end")

    summary = payload.get("summary") or {}
    practice_scores = payload.get("practice_scores") or {}
    anti_patterns = payload.get("anti_patterns") or []

    s_total_sessions = int(summary.get("total_sessions", 0) or 0)
    s_total_requests = int(summary.get("total_requests", 0) or 0)
    s_total_workspaces = int(summary.get("total_workspaces", 0) or 0)
    s_total_ai_loc = int(summary.get("total_ai_loc", 0) or 0)
    s_total_input_tokens = int(summary.get("total_input_tokens", 0) or 0)
    s_total_output_tokens = int(summary.get("total_output_tokens", 0) or 0)
    s_estimated_cost = float(summary.get("estimated_cost_usd", 0.0) or 0.0)

    # Scores may come in as {"prompt-quality": {"score": N, "weekly": [...]}}
    # or as flat {"prompt_quality": N}. Handle both.
    def _extract_score(key_hyphen: str, key_underscore: str) -> float:
        val = practice_scores.get(key_hyphen)
        if val is None:
            val = practice_scores.get(key_underscore)
        if isinstance(val, dict):
            val = val.get("score")
        try:
            return float(val) if val is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    score_pq = _extract_score("prompt-quality", "prompt_quality")
    score_sh = _extract_score("session-hygiene", "session_hygiene")
    score_cr = _extract_score("code-review", "code_review")
    score_tm = _extract_score("tool-mastery", "tool_mastery")
    score_cm = _extract_score("context-management", "context_management")
    overall = _avg([score_pq, score_sh, score_cr, score_tm, score_cm])

    with db() as conn:
        upsert_employee(conn, employee_id, name, team, email=email)

        cur = conn.execute(
            "INSERT INTO snapshots (employee_id, period_start, period_end, payload_json) "
            "VALUES (?, ?, ?, ?)",
            (employee_id, period_start, period_end, json.dumps(payload)),
        )
        snapshot_id = cur.lastrowid
        if snapshot_id is None:  # pragma: no cover - INSERT always yields a rowid
            raise RuntimeError("Failed to insert snapshot row")

        conn.execute(
            """
            INSERT INTO metrics_summary (
                employee_id, snapshot_id, period_start, period_end,
                total_sessions, total_requests, total_workspaces, total_ai_loc,
                total_input_tokens, total_output_tokens, estimated_cost_usd,
                score_prompt_quality, score_session_hygiene, score_code_review,
                score_tool_mastery, score_context_management, overall_score
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                employee_id, snapshot_id, period_start, period_end,
                s_total_sessions, s_total_requests, s_total_workspaces, s_total_ai_loc,
                s_total_input_tokens, s_total_output_tokens, s_estimated_cost,
                score_pq, score_sh, score_cr, score_tm, score_cm, overall,
            ),
        )

        # Anti-patterns: delete old ones for this snapshot first (defensive;
        # a snapshot is new, but this keeps re-ingestion of the same logical
        # snapshot id safe if ever reused).
        conn.execute("DELETE FROM anti_patterns WHERE snapshot_id = ?", (snapshot_id,))
        for ap in anti_patterns:
            triggered_val = ap.get("triggered", False)
            triggered_int = 1 if triggered_val else 0
            examples = ap.get("examples")
            examples_json = json.dumps(examples) if examples is not None else None
            conn.execute(
                """
                INSERT INTO anti_patterns (
                    employee_id, snapshot_id, rule_id, rule_name, rule_group,
                    severity, triggered, occurrences, total, examples_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    employee_id, snapshot_id,
                    ap.get("rule_id"), ap.get("rule_name"), ap.get("rule_group"),
                    ap.get("severity"), triggered_int,
                    int(ap.get("occurrences", 0) or 0), int(ap.get("total", 0) or 0),
                    examples_json,
                ),
            )

        # Store project-level data from the payload
        projects = payload.get("projects") or []
        for proj in projects:
            # Auto-clump project data from different employee machines.
            # Different local paths can hash differently, but the same repo/project
            # folder name should roll up to one mothership project by default.
            raw_pid = proj.get("project_id") or ""
            pname = proj.get("project_name") or raw_pid
            existing_by_name = None
            norm_name = _norm_project_name(pname)
            if norm_name:
                for cand in conn.execute("SELECT project_id, project_name FROM projects").fetchall():
                    if _norm_project_name(cand["project_name"]) == norm_name:
                        existing_by_name = cand
                        break
            pid = existing_by_name["project_id"] if existing_by_name else raw_pid
            if not pid:
                continue
            # Upsert project metadata (admin-assignable fields stay if already set)
            existing = conn.execute(
                "SELECT team, client, billing_code FROM projects WHERE project_id = ?",
                (pid,),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE projects SET project_name = COALESCE(project_name, ?), project_path = COALESCE(project_path, ?) WHERE project_id = ?",
                    (pname, proj.get("project_path"), pid),
                )
            else:
                conn.execute(
                    "INSERT INTO projects (project_id, project_name, project_path) VALUES (?, ?, ?)",
                    (pid, pname, proj.get("project_path")),
                )

            conn.execute(
                """
                INSERT INTO project_snapshots (
                    project_id, employee_id, snapshot_id, sessions, requests,
                    ai_loc, user_loc, input_tokens, output_tokens, estimated_cost_usd,
                    first_activity, last_activity, active_days,
                    model_usage_json, work_types_json, git_branches_json, files_edited_count
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    pid, employee_id, snapshot_id,
                    proj.get("sessions", 0), proj.get("requests", 0),
                    proj.get("ai_loc", 0), proj.get("user_loc", 0),
                    proj.get("input_tokens", 0), proj.get("output_tokens", 0),
                    proj.get("estimated_cost_usd", 0.0),
                    proj.get("first_activity"), proj.get("last_activity"),
                    proj.get("active_days", 0),
                    json.dumps(proj.get("model_usage") or {}),
                    json.dumps(proj.get("work_types") or {}),
                    json.dumps(proj.get("git_branches") or []),
                    proj.get("files_edited_count", 0),
                ),
            )

        return snapshot_id


def get_latest_snapshot_payload(conn: sqlite3.Connection, employee_id: str) -> dict[str, Any] | None:
    """Return the full parsed payload for an employee's latest snapshot."""
    row = conn.execute(
        "SELECT id, uploaded_at, payload_json FROM snapshots "
        "WHERE employee_id = ? ORDER BY id DESC LIMIT 1",
        (employee_id,),
    ).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    # Attach server-side metadata.
    payload["_snapshot_id"] = row["id"]
    payload["_uploaded_at"] = row["uploaded_at"]
    return payload


def get_anti_patterns_for_snapshot(conn: sqlite3.Connection, snapshot_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM anti_patterns WHERE snapshot_id = ? ORDER BY id",
        (snapshot_id,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _row_to_dict(r)
        d["triggered"] = bool(d["triggered"])
        # Privacy boundary: examples can contain raw employee prompts. Store
        # them for local debugging, but never return them through dashboard APIs.
        del d["examples_json"]
        out.append(d)
    return out


def get_rule_overrides() -> dict[str, dict[str, Any]]:
    """Return admin-configured rule overrides keyed by rule_id."""
    with db() as conn:
        rows = conn.execute("SELECT rule_id, enabled, severity, updated_at FROM rule_overrides").fetchall()
        return {
            r["rule_id"]: {
                "enabled": bool(r["enabled"]),
                "severity": r["severity"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        }


def set_rule_override(rule_id: str, *, enabled: bool | None = None, severity: str | None = None) -> dict[str, Any]:
    """Create/update a rule override. severity may be high/medium/low or None."""
    current = get_rule_overrides().get(rule_id, {"enabled": True, "severity": None})
    new_enabled = current.get("enabled", True) if enabled is None else bool(enabled)
    new_severity = current.get("severity") if severity is None else severity
    if new_severity not in (None, "high", "medium", "low"):
        raise ValueError("severity must be one of high, medium, low, or null")
    with db() as conn:
        conn.execute(
            """
            INSERT INTO rule_overrides (rule_id, enabled, severity, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(rule_id) DO UPDATE SET
                enabled = excluded.enabled,
                severity = excluded.severity,
                updated_at = CURRENT_TIMESTAMP
            """,
            (rule_id, 1 if new_enabled else 0, new_severity),
        )
    return {"rule_id": rule_id, "enabled": new_enabled, "severity": new_severity}


def get_plan_override(employee_id: str) -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            "SELECT plan_context_json FROM employee_plan_overrides WHERE employee_id = ?",
            (employee_id,),
        ).fetchone()
        return json.loads(row["plan_context_json"]) if row else None


def set_plan_override(employee_id: str, plan_context: dict[str, Any]) -> dict[str, Any]:
    """Set admin-confirmed plan context for an employee."""
    with db() as conn:
        if get_employee(conn, employee_id) is None:
            raise KeyError(employee_id)
        conn.execute(
            """
            INSERT INTO employee_plan_overrides (employee_id, plan_context_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(employee_id) DO UPDATE SET
                plan_context_json = excluded.plan_context_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (employee_id, json.dumps(plan_context)),
        )
    return plan_context


# ---------------------------------------------------------------------------
# Employee detail + history
# ---------------------------------------------------------------------------


def get_employee_detail(employee_id: str) -> dict[str, Any] | None:
    """Assemble the full detail view for one employee (latest snapshot)."""
    with db() as conn:
        emp = get_employee(conn, employee_id)
        if not emp:
            return None

        payload = get_latest_snapshot_payload(conn, employee_id)
        if not payload:
            return {
                "employee_id": employee_id,
                "name": emp["name"],
                "email": emp["email"],
                "team": emp["team"],
                "latest_snapshot": None,
                "summary": {},
                "practice_scores": {},
                "anti_patterns": [],
                "model_usage": {},
                "work_types": {},
                "activity": {},
                "recommendations": {"training": [], "plan": None},
            }

        snapshot_id = payload["_snapshot_id"]
        uploaded_at = payload["_uploaded_at"]

        # Use payload sections (preserved as-is) for the response.
        anti_patterns = get_anti_patterns_for_snapshot(conn, snapshot_id)

        detail = {
            "employee_id": employee_id,
            "name": emp["name"],
            "email": emp["email"],
            "team": emp["team"],
            "latest_snapshot": uploaded_at,
            "period_start": payload.get("period_start"),
            "period_end": payload.get("period_end"),
            "summary": payload.get("summary") or {},
            "practice_scores": payload.get("practice_scores") or {},
            "anti_patterns": anti_patterns,
            "model_usage": payload.get("model_usage") or {},
            "work_types": payload.get("work_types") or {},
            "activity": payload.get("activity") or {},
            "plan_context": payload.get("plan_context") or {},
        }

        # Recommendations computed from the assembled data.
        from recommendations import recommendations_for_employee

        rec_input = {
            "summary": detail["summary"],
            "practice_scores": detail["practice_scores"],
            "anti_patterns": anti_patterns,
            "plan_context": detail.get("plan_context") or {},
        }
        detail["recommendations"] = recommendations_for_employee(rec_input)
        return detail


def get_employee_history(employee_id: str) -> list[dict[str, Any]]:
    """Return score history for an employee from metrics_summary."""
    with db() as conn:
        rows = conn.execute(
            """
            SELECT ms.snapshot_id, s.uploaded_at, ms.period_start, ms.period_end,
                   ms.overall_score, ms.score_prompt_quality, ms.score_session_hygiene,
                   ms.score_code_review, ms.score_tool_mastery, ms.score_context_management
            FROM metrics_summary ms
            JOIN snapshots s ON s.id = ms.snapshot_id
            WHERE ms.employee_id = ?
            ORDER BY ms.snapshot_id ASC
            """,
            (employee_id,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "snapshot_id": r["snapshot_id"],
                    "uploaded_at": r["uploaded_at"],
                    "period_start": r["period_start"],
                    "period_end": r["period_end"],
                    "overall_score": r["overall_score"],
                    "scores": {
                        "prompt_quality": r["score_prompt_quality"],
                        "session_hygiene": r["score_session_hygiene"],
                        "code_review": r["score_code_review"],
                        "tool_mastery": r["score_tool_mastery"],
                        "context_management": r["score_context_management"],
                    },
                }
            )
        return out


# ---------------------------------------------------------------------------
# Team overview
# ---------------------------------------------------------------------------


def get_team_overview() -> dict[str, Any]:
    """Aggregate team-wide stats from each employee's latest snapshot."""
    with db() as conn:
        employees = conn.execute("SELECT id, name, team FROM employees").fetchall()
        total_employees = len(employees)
        if total_employees == 0:
            return {
                "total_employees": 0,
                "total_requests": 0,
                "total_cost_usd": 0.0,
                "avg_overall_score": 0.0,
                "team_breakdown": {},
                "top_training_needs": [],
                "plan_recommendations": [],
                "score_distribution": {
                    "excellent": 0,
                    "good": 0,
                    "needs_improvement": 0,
                    "at_risk": 0,
                },
            }

        # Gather per-employee latest snapshot data.
        per_employee: list[dict[str, Any]] = []
        for emp in employees:
            eid = emp["id"]
            snap = conn.execute(
                "SELECT id FROM snapshots WHERE employee_id = ? ORDER BY id DESC LIMIT 1",
                (eid,),
            ).fetchone()
            if not snap:
                continue
            m = conn.execute(
                "SELECT * FROM metrics_summary WHERE snapshot_id = ? LIMIT 1",
                (snap["id"],),
            ).fetchone()
            if not m:
                continue
            aps = get_anti_patterns_for_snapshot(conn, snap["id"])
            per_employee.append(
                {
                    "employee_id": eid,
                    "team": emp["team"],
                    "total_requests": m["total_requests"],
                    "estimated_cost_usd": m["estimated_cost_usd"],
                    "overall_score": m["overall_score"],
                    "anti_patterns": aps,
                    "summary": {
                        "total_requests": m["total_requests"],
                        "estimated_cost_usd": m["estimated_cost_usd"],
                    },
                    "practice_scores": {
                        "prompt_quality": m["score_prompt_quality"],
                        "session_hygiene": m["score_session_hygiene"],
                        "code_review": m["score_code_review"],
                        "tool_mastery": m["score_tool_mastery"],
                        "context_management": m["score_context_management"],
                    },
                }
            )

        total_requests = sum(int(e["total_requests"] or 0) for e in per_employee)
        total_cost = round(sum(float(e["estimated_cost_usd"] or 0) for e in per_employee), 2)
        scores = [float(e["overall_score"] or 0) for e in per_employee]
        avg_score = round(sum(scores) / len(scores), 2) if scores else 0.0

        # Team breakdown.
        team_breakdown: dict[str, dict[str, Any]] = {}
        for e in per_employee:
            t = e["team"] or "unassigned"
            tb = team_breakdown.setdefault(t, {"employees": 0, "avg_score": 0.0, "total_cost": 0.0, "total_requests": 0, "_scores": []})
            tb["employees"] += 1
            tb["total_cost"] = round(tb["total_cost"] + float(e["estimated_cost_usd"] or 0), 2)
            tb["total_requests"] += int(e["total_requests"] or 0)
            tb["_scores"].append(float(e["overall_score"] or 0))
        for t, tb in team_breakdown.items():
            tb["avg_score"] = round(sum(tb["_scores"]) / len(tb["_scores"]), 2) if tb["_scores"] else 0.0
            del tb["_scores"]

        # Score distribution buckets (aligned with frontend: 80/60/40).
        def bucket(s: float) -> str:
            if s >= 80:
                return "excellent"
            if s >= 60:
                return "good"
            if s >= 40:
                return "needs_improvement"
            return "at_risk"

        score_distribution = {"excellent": 0, "good": 0, "needs_improvement": 0, "at_risk": 0}
        for s in scores:
            score_distribution[bucket(s)] += 1

        # Top training needs: aggregate training recommendations across team.
        from recommendations import training_recommendations

        all_recs: list[dict[str, Any]] = []
        for e in per_employee:
            recs = training_recommendations(e["anti_patterns"])
            for r in recs:
                all_recs.append(r)

        # Aggregate by track.
        track_agg: dict[str, dict[str, Any]] = {}
        for r in all_recs:
            track = r["track"]
            ta = track_agg.setdefault(
                track,
                {"track": track, "employees_needing": 0, "modules": set(), "_severities": []},
            )
            ta["employees_needing"] += 1
            ta["modules"].add(r["module"])
            ta["_severities"].append(r["severity"])
        # Determine avg severity per track (highest common severity).
        sev_rank = {"high": 0, "medium": 1, "low": 2}
        top_training_needs: list[dict[str, Any]] = []
        for track, ta in track_agg.items():
            sev_counts = {"high": 0, "medium": 0, "low": 0}
            for s in ta["_severities"]:
                sev_counts[s] = sev_counts.get(s, 0) + 1
            # Avg severity = the modal severity, leaning high.
            if sev_counts["high"] > 0:
                avg_sev = "high"
            elif sev_counts["medium"] > 0:
                avg_sev = "medium"
            else:
                avg_sev = "low"
            top_training_needs.append(
                {
                    "track": track,
                    "employees_needing": ta["employees_needing"],
                    "avg_severity": avg_sev,
                    "modules": sorted(ta["modules"]),
                }
            )
        top_training_needs.sort(key=lambda x: (sev_rank.get(x["avg_severity"], 9), -x["employees_needing"]))

        # Plan recommendations for each employee.
        from recommendations import recommend_plan

        plan_recommendations: list[dict[str, Any]] = []
        for e in per_employee:
            rec = recommend_plan(e)
            plan_recommendations.append(
                {
                    "employee_id": e["employee_id"],
                    "recommendation": rec["action"],
                    "plan": rec["plan"],
                    "reason": rec["reason"],
                }
            )
        # Sort: upgrade first, then train_first, review, maintain.
        action_order = {"upgrade": 0, "train_first": 1, "review": 2, "maintain": 3}
        plan_recommendations.sort(key=lambda x: action_order.get(x["recommendation"], 9))

        return {
            "total_employees": total_employees,
            "total_requests": total_requests,
            "total_cost_usd": total_cost,
            "avg_overall_score": avg_score,
            "team_breakdown": team_breakdown,
            "top_training_needs": top_training_needs,
            "plan_recommendations": plan_recommendations,
            "score_distribution": score_distribution,
        }


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def count_employees() -> int:
    with db() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM employees").fetchone()
        return row["c"] if row else 0


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------


def get_all_projects() -> list[dict[str, Any]]:
    """Return all projects with cross-employee aggregated stats from latest snapshots.

    Clubs project_snapshots from various employees working on the same project,
    taking each employee's latest snapshot to avoid double-counting.
    """
    with db() as conn:
        # Get each employee's latest snapshot_id
        latest_snapshots = conn.execute(
            """
            SELECT s.employee_id, MAX(s.id) AS snapshot_id
            FROM snapshots s
            GROUP BY s.employee_id
            """
        ).fetchall()
        if not latest_snapshots:
            return []

        snap_ids = [r["snapshot_id"] for r in latest_snapshots]
        placeholders = ",".join("?" * len(snap_ids))

        rows = conn.execute(
            f"""
            SELECT ps.project_id, p.project_name, p.project_path, p.team, p.client, p.billing_code,
                   ps.employee_id, ps.sessions, ps.requests, ps.ai_loc, ps.user_loc,
                   ps.input_tokens, ps.output_tokens, ps.estimated_cost_usd,
                   ps.first_activity, ps.last_activity, ps.active_days,
                   ps.model_usage_json, ps.work_types_json, ps.git_branches_json, ps.files_edited_count,
                   e.name AS employee_name, e.email AS employee_email, e.team AS employee_team
            FROM project_snapshots ps
            JOIN projects p ON p.project_id = ps.project_id
            JOIN employees e ON e.id = ps.employee_id
            WHERE ps.snapshot_id IN ({placeholders})
            ORDER BY ps.project_id, ps.estimated_cost_usd DESC
            """,
            snap_ids,
        ).fetchall()

        # Group by project_id, aggregating across employees
        projects_map: dict[str, dict[str, Any]] = {}
        for r in rows:
            pid = r["project_id"]
            if pid not in projects_map:
                projects_map[pid] = {
                    "project_id": pid,
                    "project_name": r["project_name"],
                    "project_path": r["project_path"],
                    "team": r["team"],
                    "client": r["client"],
                    "billing_code": r["billing_code"],
                    "employees": [],
                    "total_sessions": 0,
                    "total_requests": 0,
                    "total_ai_loc": 0,
                    "total_user_loc": 0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "total_cost_usd": 0.0,
                    "first_activity": "",
                    "last_activity": "",
                    "active_days": 0,
                    "files_edited_count": 0,
                    "model_usage": {},
                    "work_types": {},
                }
            proj = projects_map[pid]
            proj["employees"].append({
                "employee_id": r["employee_id"],
                "employee_name": r["employee_name"],
                "employee_email": r["employee_email"],
                "team": r["employee_team"],
                "sessions": r["sessions"],
                "requests": r["requests"],
                "ai_loc": r["ai_loc"],
                "cost_usd": r["estimated_cost_usd"],
                "active_days": r["active_days"],
            })
            proj["total_sessions"] += r["sessions"] or 0
            proj["total_requests"] += r["requests"] or 0
            proj["total_ai_loc"] += r["ai_loc"] or 0
            proj["total_user_loc"] += r["user_loc"] or 0
            proj["total_input_tokens"] += r["input_tokens"] or 0
            proj["total_output_tokens"] += r["output_tokens"] or 0
            proj["total_cost_usd"] += r["estimated_cost_usd"] or 0.0
            proj["active_days"] = max(proj["active_days"], r["active_days"] or 0)
            proj["files_edited_count"] += r["files_edited_count"] or 0
            if r["first_activity"] and (not proj["first_activity"] or r["first_activity"] < proj["first_activity"]):
                proj["first_activity"] = r["first_activity"]
            if r["last_activity"] and (not proj["last_activity"] or r["last_activity"] > proj["last_activity"]):
                proj["last_activity"] = r["last_activity"]
            # Merge model_usage and work_types
            for k, v in (json.loads(r["model_usage_json"] or "{}")).items():
                proj["model_usage"][k] = proj["model_usage"].get(k, 0) + v
            for k, v in (json.loads(r["work_types_json"] or "{}")).items():
                proj["work_types"][k] = proj["work_types"].get(k, 0) + v

        result = list(projects_map.values())
        result.sort(key=lambda p: p["total_cost_usd"], reverse=True)
        return result


def get_project_detail(project_id: str) -> dict[str, Any] | None:
    """Return detail for one project, including per-employee breakdown."""
    projects = get_all_projects()
    for p in projects:
        if p["project_id"] == project_id:
            return p
    return None


def update_project_metadata(project_id: str, team: str | None = None, client: str | None = None, billing_code: str | None = None, project_name: str | None = None) -> bool:
    """Admin-update of project metadata (name, team, client, billing code)."""
    with db() as conn:
        existing = conn.execute("SELECT project_id FROM projects WHERE project_id = ?", (project_id,)).fetchone()
        if not existing:
            return False
        _maybe_upsert_team(conn, team)
        _maybe_upsert_client(conn, client)
        updates: list[str] = []
        params: list[Any] = []
        if project_name is not None:
            updates.append("project_name = ?")
            params.append(project_name)
        if team is not None:
            updates.append("team = ?")
            params.append(team)
        if client is not None:
            updates.append("client = ?")
            params.append(client)
        if billing_code is not None:
            updates.append("billing_code = ?")
            params.append(billing_code)
        if not updates:
            return True
        params.append(project_id)
        conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE project_id = ?", params)
        return True


def list_teams() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT t.name, t.description,
                   COUNT(DISTINCT e.id) AS employees,
                   COUNT(DISTINCT p.project_id) AS projects
            FROM teams t
            LEFT JOIN employees e ON e.team = t.name
            LEFT JOIN projects p ON p.team = t.name
            GROUP BY t.name, t.description
            UNION
            SELECT COALESCE(e.team, 'Unassigned') AS name, NULL AS description,
                   COUNT(DISTINCT e.id) AS employees,
                   0 AS projects
            FROM employees e
            WHERE e.team IS NOT NULL AND e.team NOT IN (SELECT name FROM teams)
            GROUP BY e.team
            ORDER BY name
            """
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def upsert_team(name: str, description: str | None = None) -> dict[str, Any]:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO teams (name, description, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET description = COALESCE(excluded.description, teams.description), updated_at = CURRENT_TIMESTAMP
            """,
            (name, description),
        )
    return {"name": name, "description": description}


def list_clients() -> list[dict[str, Any]]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT c.name, c.description, COUNT(DISTINCT p.project_id) AS projects,
                   COALESCE(SUM(ps.estimated_cost_usd), 0) AS cost_usd
            FROM clients c
            LEFT JOIN projects p ON p.client = c.name
            LEFT JOIN project_snapshots ps ON ps.project_id = p.project_id
            GROUP BY c.name, c.description
            UNION
            SELECT p.client AS name, NULL AS description, COUNT(DISTINCT p.project_id) AS projects,
                   COALESCE(SUM(ps.estimated_cost_usd), 0) AS cost_usd
            FROM projects p
            LEFT JOIN project_snapshots ps ON ps.project_id = p.project_id
            WHERE p.client IS NOT NULL AND p.client != '' AND p.client NOT IN (SELECT name FROM clients)
            GROUP BY p.client
            ORDER BY name
            """
        ).fetchall()
        return [_row_to_dict(r) for r in rows]


def upsert_client(name: str, description: str | None = None) -> dict[str, Any]:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO clients (name, description, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(name) DO UPDATE SET description = COALESCE(excluded.description, clients.description), updated_at = CURRENT_TIMESTAMP
            """,
            (name, description),
        )
    return {"name": name, "description": description}
