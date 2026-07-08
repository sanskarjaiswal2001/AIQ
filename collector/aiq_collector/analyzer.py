"""
Analyzer — orchestrates parser, rules, and scoring into the final metrics JSON.

Takes a list of :class:`~collector.models.Session` objects (produced by any
collector harness parser) and emits the dashboard-ingest JSON structure defined
in the collector spec.

Stdlib-only.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from .models import Session, SessionRequest
from .rules import run_all_rules
from .scoring import (
    aggregate_model_usage,
    compute_practice_scores,
    estimate_request_cost,
    normalize_model_id,
)

# ---------------------------------------------------------------------------
# Work-type classification  (from AIEC helpers.ts classifyWorkType)
# ---------------------------------------------------------------------------

WORK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(fix|bug|error|issue|crash|exception|debug|problem|broken|fail|wrong)\b", re.IGNORECASE), "bug fix"),
    (re.compile(r"\b(refactor|rename|extract|move|cleanup|simplify|restructure|reorganize)\b", re.IGNORECASE), "refactor"),
    (re.compile(r"\b(review|pr|pull request|code review|comment on|feedback|approve)\b", re.IGNORECASE), "code review"),
    (re.compile(r"\b(test|spec|expect|assert|mock|stub|coverage|vitest|jest|pytest|unittest)\b", re.IGNORECASE), "test"),
    (re.compile(r"\b(doc|readme|comment|explain|jsdoc|typedoc|docstring|swagger|openapi)\b", re.IGNORECASE), "docs"),
    (re.compile(r"\b(style|css|scss|sass|theme|layout|padding|margin|font|color|design|ui)\b", re.IGNORECASE), "style"),
    (re.compile(r"\b(config|setup|install|dependency|package|ci|cd|pipeline|deploy|docker|k8s|terraform|bicep|env|yaml|yml)\b", re.IGNORECASE), "config"),
    (re.compile(r"\b(add|create|implement|build|feature|new|scaffold|generate|develop)\b", re.IGNORECASE), "feature"),
]


def classify_work_type(message: str) -> str:
    """Classify a prompt into a work type. First regex match wins; default 'other'."""
    for pattern, label in WORK_PATTERNS:
        if pattern.search(message):
            return label
    return "other"



def normalize_git_remote_url(url: str | None) -> str:
    """Normalize SSH/HTTPS git remotes to host/org/repo for project identity matching."""
    raw = (url or "").strip()
    if not raw:
        return ""
    raw = raw.replace("git+", "")
    raw = re.sub(r"^[a-z]+://", "", raw, flags=re.IGNORECASE)
    raw = raw.replace("git@", "")
    raw = raw.replace(":", "/", 1) if re.match(r"^[^/]+:[^/]+/", raw) else raw
    raw = raw.split("?", 1)[0].split("#", 1)[0].strip("/")
    if raw.endswith(".git"):
        raw = raw[:-4]
    return raw.lower()


def git_remote_from_workspace(path: str | None) -> str:
    """Read .git/config from a workspace or parent folder without shelling out."""
    if not path:
        return ""
    try:
        cur = Path(os.path.expanduser(path)).resolve()
    except OSError:
        return ""
    for base in [cur, *cur.parents]:
        cfg = base / ".git" / "config"
        if not cfg.exists():
            continue
        try:
            text = cfg.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
        in_origin = False
        fallback = ""
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("["):
                in_origin = stripped.lower() == '[remote "origin"]'
                continue
            if stripped.startswith("url") and "=" in stripped:
                val = stripped.split("=", 1)[1].strip()
                fallback = fallback or val
                if in_origin:
                    return val
        return fallback
    return ""

# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class Analyzer:
    """Orchestrates parsing-derived sessions through rules + scoring and builds
    the final metrics JSON structure.

    Usage::

        from .harnesses import collect_sessions
        from .analyzer import Analyzer

        sessions = collect_sessions("auto")
        metrics = Analyzer().analyze(sessions)
    """

    def analyze(
        self,
        sessions: list[Session],
        *,
        employee_id: str = "",
        employee_name: str = "",
        period_start: str = "",
        period_end: str = "",
        plan_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run full analysis and return the dashboard-ingest JSON dict."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Derive period from session timestamps if not supplied
        if not period_start or not period_end:
            ps, pe = self._derive_period(sessions)
            period_start = period_start or ps
            period_end = period_end or pe

        summary = self._build_summary(sessions)
        practice_scores = compute_practice_scores(sessions)
        anti_patterns = [r.to_dict() for r in run_all_rules(sessions)]
        plan_context = plan_context or {}
        anti_patterns.extend(self._build_plan_anti_patterns(summary, plan_context))
        model_usage = aggregate_model_usage(sessions)
        work_types = self._build_work_types(sessions)
        activity = self._build_activity(sessions)
        projects = self._build_projects(sessions)

        return {
            "employee_id": employee_id,
            "employee_name": employee_name,
            "collected_at": now,
            "period_start": period_start,
            "period_end": period_end,
            "summary": summary,
            "practice_scores": practice_scores,
            "anti_patterns": anti_patterns,
            "model_usage": model_usage,
            "work_types": work_types,
            "activity": activity,
            "projects": projects,
            "plan_context": plan_context,
        }

    # -- plan-aware anti-patterns ------------------------------------------

    @staticmethod
    def project_id_from_path(workspace_path: str) -> str:
        """Deterministic project ID from decoded workspace path (SHA-256, first 12 hex)."""
        if not workspace_path:
            return "unknown"
        return hashlib.sha256(workspace_path.encode("utf-8")).hexdigest()[:12]

    def _build_projects(self, sessions: list[Session]) -> list[dict[str, Any]]:
        """Group sessions by project (decoded workspace path) and aggregate per-project metrics.

        This is the core of project-level financial intelligence: it clubs sessions
        from the same workspace together so the mothership can later cross-reference
        across employees working on the same project.
        """
        projects: dict[str, dict[str, Any]] = defaultdict(lambda: {
            "project_id": "",
            "project_name": "",
            "project_path": "",
            "sessions": 0,
            "requests": 0,
            "ai_loc": 0,
            "user_loc": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": 0.0,
            "first_activity": "",
            "last_activity": "",
            "active_days": set(),
            "models": Counter(),
            "work_types": Counter(),
            "git_branches": set(),
            "files_edited": set(),
            "harness_usage": Counter(),
            "git_remote_url": "",
            "normalized_git_remote": "",
        })

        for s in sessions:
            ws_path = s.workspace_path or s.workspace_name or "unknown"
            remote_url = s.git_remote_url or git_remote_from_workspace(s.workspace_path)
            normalized_remote = normalize_git_remote_url(remote_url)
            pid = normalized_remote or self.project_id_from_path(ws_path)
            proj = projects[pid]
            proj["project_id"] = pid
            proj["project_name"] = s.workspace_name or "unknown"
            proj["project_path"] = ws_path
            proj["git_remote_url"] = proj["git_remote_url"] or remote_url
            proj["normalized_git_remote"] = proj["normalized_git_remote"] or normalized_remote
            proj["sessions"] += 1
            proj["harness_usage"][s.harness or "unknown"] += 1
            proj["requests"] += s.request_count
            proj["ai_loc"] += s.total_ai_loc
            proj["user_loc"] += sum(r.user_loc for r in s.requests)
            proj["input_tokens"] += s.total_input_tokens
            proj["output_tokens"] += s.total_output_tokens
            proj["estimated_cost_usd"] += sum(estimate_request_cost(r) for r in s.requests)
            if s.git_branch:
                proj["git_branches"].add(s.git_branch)
            for r in s.requests:
                proj["models"][r.model or "<synthetic>"] += 1
                proj["work_types"][classify_work_type(r.message)] += 1
                proj["files_edited"].update(r.edited_files)
                dt = r.timestamp_dt
                if dt:
                    day = dt.strftime("%Y-%m-%d")
                    proj["active_days"].add(day)
                    day_str = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
                    if not proj["first_activity"] or day_str < proj["first_activity"]:
                        proj["first_activity"] = day_str
                    if not proj["last_activity"] or day_str > proj["last_activity"]:
                        proj["last_activity"] = day_str

        # Finalize — convert sets/Counters to serializable structures
        result: list[dict[str, Any]] = []
        for pid, proj in projects.items():
            result.append({
                "project_id": proj["project_id"],
                "project_name": proj["project_name"],
                "project_path": proj["project_path"],
                "sessions": proj["sessions"],
                "requests": proj["requests"],
                "ai_loc": proj["ai_loc"],
                "user_loc": proj["user_loc"],
                "input_tokens": proj["input_tokens"],
                "output_tokens": proj["output_tokens"],
                "estimated_cost_usd": round(proj["estimated_cost_usd"], 4),
                "first_activity": proj["first_activity"],
                "last_activity": proj["last_activity"],
                "active_days": len(proj["active_days"]),
                "model_usage": dict(proj["models"]),
                "work_types": dict(proj["work_types"]),
                "git_branches": sorted(proj["git_branches"]),
                "files_edited_count": len(proj["files_edited"]),
                "git_remote_url": proj["git_remote_url"],
                "normalized_git_remote": proj["normalized_git_remote"],
                "harness_usage": dict(proj["harness_usage"]),
            })
        result.sort(key=lambda p: p["estimated_cost_usd"], reverse=True)
        return result

    # -- plan-aware anti-patterns (continued)

    def _build_plan_anti_patterns(self, summary: dict[str, Any], plan_context: dict[str, Any]) -> list[dict[str, Any]]:
        """Synthetic rules that need billing/plan context, not just logs.

        Rolling-window enterprise seats (for example a Claude team/enterprise
        seat with a $25 rolling window) behave differently from API billing:
        the relevant signal is quota pressure, not token-estimated invoice.
        """
        if not plan_context:
            return []
        plan_type = str(plan_context.get("plan_type") or plan_context.get("billing_mode") or "").lower()
        est_cost = float(summary.get("estimated_cost_usd", 0.0) or 0.0)
        window_usd = float(plan_context.get("rolling_window_usd", 0.0) or plan_context.get("quota_usd", 0.0) or 0.0)
        window_days = int(plan_context.get("rolling_window_days", 0) or 0)
        out: list[dict[str, Any]] = []
        if "rolling" in plan_type and window_usd > 0:
            utilization = est_cost / window_usd
            triggered = utilization >= 0.85
            out.append({
                "rule_id": "rolling-window-pressure",
                "name": "Rolling Window Pressure",
                "rule_name": "Rolling Window Pressure",
                "group": "plan-efficiency",
                "rule_group": "plan-efficiency",
                "severity": "high" if utilization >= 1 else "medium",
                "description": "Estimated usage is close to or above the employee rolling-window quota.",
                "suggestion": "Review whether this user needs a higher seat/quota, workflow training, or better model routing before they hit the rolling cap.",
                "triggered": triggered,
                "occurrences": round(utilization * 100),
                "total": 100,
                "examples": [f"estimated ${est_cost:.2f} / ${window_usd:.2f}" + (f" per {window_days}d window" if window_days else " rolling window")],
                "metadata": {"utilization": round(utilization, 4), "window_usd": window_usd, "window_days": window_days},
            })
        return out

    # -- summary ------------------------------------------------------------

    def _build_summary(self, sessions: list[Session]) -> dict[str, Any]:
        total_requests = sum(s.request_count for s in sessions)
        workspaces = {s.workspace_name for s in sessions}
        total_ai_loc = sum(s.total_ai_loc for s in sessions)
        total_user_loc = sum(
            r.user_loc for s in sessions for r in s.requests
        )
        total_input_tokens = sum(s.total_input_tokens for s in sessions)
        total_output_tokens = sum(s.total_output_tokens for s in sessions)
        total_cost = sum(
            estimate_request_cost(r) for s in sessions for r in s.requests
        )
        return {
            "total_sessions": len(sessions),
            "total_requests": total_requests,
            "total_workspaces": len(workspaces),
            "total_ai_loc": total_ai_loc,
            "total_user_loc": total_user_loc,
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "estimated_cost_usd": round(total_cost, 4),
        }

    # -- work types ---------------------------------------------------------

    def _build_work_types(self, sessions: list[Session]) -> dict[str, int]:
        counts: Counter[str] = Counter()
        for s in sessions:
            for r in s.requests:
                counts[classify_work_type(r.message)] += 1
        return dict(counts)

    # -- activity -----------------------------------------------------------

    def _build_activity(self, sessions: list[Session]) -> dict[str, Any]:
        daily: dict[str, dict[str, int]] = defaultdict(
            lambda: {"requests": 0, "sessions": 0, "ai_loc": 0}
        )
        hourly_heatmap: list[list[int]] = [[0] * 24 for _ in range(7)]
        workspaces: dict[str, dict[str, int]] = defaultdict(
            lambda: {"requests": 0, "sessions": 0, "ai_loc": 0}
        )

        # track which sessions touched each day to avoid double-counting
        day_sessions: dict[str, set[str]] = defaultdict(set)
        ws_sessions: dict[str, set[str]] = defaultdict(set)

        for s in sessions:
            ws = s.workspace_name
            ws_sessions[ws].add(s.session_id)
            workspaces[ws]["ai_loc"] += s.total_ai_loc

            for r in s.requests:
                dt = r.timestamp_dt
                if dt is None:
                    continue
                day = dt.strftime("%Y-%m-%d")
                daily[day]["requests"] += 1
                daily[day]["ai_loc"] += r.ai_loc
                day_sessions[day].add(s.session_id)
                # weekday=0 (Mon) .. 6 (Sun); hour 0..23
                hourly_heatmap[dt.weekday()][dt.hour] += 1
                workspaces[ws]["requests"] += 1

        # finalize session counts
        for day, sids in day_sessions.items():
            daily[day]["sessions"] = len(sids)
        for ws, sids in ws_sessions.items():
            workspaces[ws]["sessions"] = len(sids)

        return {
            "daily": dict(sorted(daily.items())),
            "hourly_heatmap": hourly_heatmap,
            "workspaces": dict(workspaces),
        }

    # -- helpers ------------------------------------------------------------

    def _derive_period(self, sessions: list[Session]) -> tuple[str, str]:
        """Derive period_start / period_end (YYYY-MM-DD) from session timestamps."""
        dates: list[str] = []
        for s in sessions:
            for r in s.requests:
                if r.timestamp_dt:
                    dates.append(r.timestamp_dt.strftime("%Y-%m-%d"))
        if not dates:
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            return today, today
        dates.sort()
        return dates[0], dates[-1]
