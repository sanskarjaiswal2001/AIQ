"""
Analyzer — orchestrates parser, rules, and scoring into the final metrics JSON.

Takes a list of :class:`~collector.models.Session` objects (produced by
:class:`~collector.parser.ClaudeLogParser`) and emits the dashboard-ingest
JSON structure defined in the collector spec.

Stdlib-only.
"""

from __future__ import annotations

import re
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


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class Analyzer:
    """Orchestrates parsing-derived sessions through rules + scoring and builds
    the final metrics JSON structure.

    Usage::

        from .parser import ClaudeLogParser
        from .analyzer import Analyzer

        sessions = ClaudeLogParser().parse_directory()
        metrics = Analyzer().analyze(sessions)
    """

    def analyze(
        self,
        sessions: list[Session],
        *,
        employee_id: str = "",
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

        return {
            "employee_id": employee_id,
            "collected_at": now,
            "period_start": period_start,
            "period_end": period_end,
            "summary": summary,
            "practice_scores": practice_scores,
            "anti_patterns": anti_patterns,
            "model_usage": model_usage,
            "work_types": work_types,
            "activity": activity,
            "plan_context": plan_context,
        }

    # -- plan-aware anti-patterns ------------------------------------------

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
