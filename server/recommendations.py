"""Recommendation engine for the AIECO dashboard.

Two responsibilities:
  1. ``training_recommendations`` — map triggered anti-patterns to specific
     training modules, sorted by severity then occurrences, top 5.
  2. ``recommend_plan`` — decide whether an employee should upgrade, train
     first, maintain, or downgrade their AI plan based on usage, cost, and
     efficiency signals.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Anti-pattern group -> training track/module mapping
# ---------------------------------------------------------------------------

TRAINING_MAP: dict[str, dict[str, str]] = {
    "lazy-prompting": {"track": "Prompt Engineering", "module": "Writing Effective Prompts", "priority": "high"},
    "repeated-prompts": {"track": "Prompt Engineering", "module": "Iterative Prompting Techniques", "priority": "medium"},
    "no-spec-driven-development": {"track": "Prompt Engineering", "module": "Spec-Driven Development", "priority": "high"},
    "verbose-prompt-no-compression": {"track": "Prompt Engineering", "module": "Prompt Compression & Context", "priority": "medium"},
    "no-plan-mode": {"track": "Prompt Engineering", "module": "Using Plan Mode Effectively", "priority": "low"},
    "no-skills": {"track": "Prompt Engineering", "module": "Creating Reusable Skills", "priority": "medium"},

    "speed-accept": {"track": "AI Code Review", "module": "Reviewing AI-Generated Code", "priority": "high"},
    "copy-paste-blindness": {"track": "AI Code Review", "module": "Validating Generated Code", "priority": "high"},

    "premium-waste": {"track": "Model & Tool Selection", "module": "Cost-Aware Model Routing", "priority": "high"},
    "premium-for-lookup-questions": {"track": "Model & Tool Selection", "module": "Choosing the Right Model", "priority": "medium"},
    "model-overreliance": {"track": "Model & Tool Selection", "module": "Multi-Model Workflows", "priority": "medium"},
    "rolling-window-pressure": {"track": "Model & Tool Selection", "module": "Rolling Window Budget Management", "priority": "high"},

    "runaway-agent-loops": {"track": "Agent Orchestration", "module": "Managing Agent Loops", "priority": "high"},
    "session-drift": {"track": "Agent Orchestration", "module": "Session Management", "priority": "medium"},
    "mega-sessions": {"track": "Agent Orchestration", "module": "Breaking Down Complex Tasks", "priority": "medium"},

    "context-engineering-gaps": {"track": "Context Engineering", "module": "Setting Up AGENTS.md & Skills", "priority": "high"},

    "high-cancellation": {"track": "Workflow Optimization", "module": "Reducing Cancellations", "priority": "medium"},
    "frustration-signals": {"track": "Workflow Optimization", "module": "Managing AI Frustration", "priority": "medium"},
    "tunnel-vision": {"track": "Workflow Optimization", "module": "Diversifying Project Context", "priority": "low"},

    "late-night-coding": {"track": "Work-Life Balance", "module": "Sustainable AI Usage", "priority": "low"},
    "weekend-overwork": {"track": "Work-Life Balance", "module": "Sustainable AI Usage", "priority": "low"},
}

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def _severity_rank(sev: str | None) -> int:
    if not sev:
        return 3
    return _SEVERITY_RANK.get(str(sev).lower(), 3)


# ---------------------------------------------------------------------------
# Training recommendations
# ---------------------------------------------------------------------------


def training_recommendations(anti_patterns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a sorted list of training recommendations from triggered anti-patterns.

    Each anti-pattern that is *triggered* is mapped (via its ``rule_group``)
    to a training track/module. Results are sorted by:
      1. severity (high > medium > low)
      2. occurrences (descending)
    and capped at the top 5. Duplicate (track, module) recommendations are
    merged, keeping the highest severity / occurrence count.
    """
    seen: dict[tuple[str, str], dict[str, Any]] = {}

    for ap in anti_patterns:
        # Normalise: accept either triggered flag or triggered int (0/1).
        triggered = ap.get("triggered", False)
        if isinstance(triggered, int):
            triggered = bool(triggered)
        if not triggered:
            continue

        rule_id = ap.get("rule_id")
        if not rule_id:
            continue

        entry = TRAINING_MAP.get(rule_id)
        if not entry:
            # Unknown rule — still surface a generic recommendation.
            track = "General AI Efficiency"
            module = ap.get("rule_name") or rule_id or "General Best Practices"
            priority = ap.get("severity") or "medium"
        else:
            track = entry["track"]
            module = entry["module"]
            priority = entry["priority"]

        sev = ap.get("severity") or priority
        if sev in {"high", "medium", "low"}:
            priority = sev
        occ = int(ap.get("occurrences", 0) or 0)

        key = (track, module)
        existing = seen.get(key)
        if existing is None:
            seen[key] = {
                "track": track,
                "module": module,
                "priority": priority,
                "severity": sev,
                "occurrences": occ,
                "rule_ids": [rule_id] if rule_id else [],
            }
        else:
            # Merge: keep the more severe / higher-occurrence representation.
            if _severity_rank(sev) < _severity_rank(existing["severity"]):
                existing["severity"] = sev
                existing["priority"] = priority
            existing["occurrences"] = max(existing["occurrences"], occ)
            if rule_id and rule_id not in existing["rule_ids"]:
                existing["rule_ids"].append(rule_id)

    recs = list(seen.values())
    recs.sort(key=lambda r: (_severity_rank(r["severity"]), -r["occurrences"]))
    return recs[:5]


# ---------------------------------------------------------------------------
# Plan recommendation
# ---------------------------------------------------------------------------


def recommend_plan(employee_data: dict[str, Any]) -> dict[str, Any]:
    """Recommend a plan action for an employee.

    ``employee_data`` should contain ``summary``, ``practice_scores`` (or the
    flattened score fields), and ``anti_patterns``. It tolerates either the
    nested form (as stored in payload_json) or the partially-flattened form
    used by some endpoints.
    """
    summary = employee_data.get("summary") or {}
    anti_patterns = employee_data.get("anti_patterns") or []
    plan_context = employee_data.get("plan_context") or {}

    cost = float(summary.get("estimated_cost_usd", 0.0) or 0.0)
    requests = int(summary.get("total_requests", 0) or 0)
    plan_type = str(plan_context.get("plan_type") or "api").lower()
    billing_mode = str(plan_context.get("billing_mode") or "").lower()
    rolling_window_usd = float(plan_context.get("rolling_window_usd", 0.0) or plan_context.get("quota_usd", 0.0) or 0.0)
    is_rolling = "rolling" in plan_type or "rolling" in billing_mode

    # Overall score: prefer a precomputed value, else average the 5 scores.
    overall_score = employee_data.get("overall_score")
    if overall_score is None:
        ps = employee_data.get("practice_scores") or {}
        if ps:
            # Handle nested {"prompt-quality": {"score": N}} format
            def _score(key):
                v = ps.get(key)
                if isinstance(v, dict):
                    v = v.get("score")
                try:
                    return float(v) if v is not None else 0.0
                except (TypeError, ValueError):
                    return 0.0
            scores = [
                _score("prompt-quality"),
                _score("session-hygiene"),
                _score("code-review"),
                _score("tool-mastery"),
                _score("context-management"),
            ]
            overall_score = sum(scores) / len(scores) if scores else 0.0
        else:
            overall_score = 0.0
    overall_score = float(overall_score)

    premium_waste_triggered = any(
        ap.get("rule_id") == "premium-waste" and bool(ap.get("triggered", False)) for ap in anti_patterns
    )
    model_overreliance_triggered = any(
        ap.get("rule_id") == "model-overreliance"
        and bool(ap.get("triggered", False))
        and str(ap.get("severity") or "medium").lower() != "low"
        for ap in anti_patterns
    )
    rolling_pressure_triggered = any(
        ap.get("rule_id") == "rolling-window-pressure" and bool(ap.get("triggered", False)) for ap in anti_patterns
    )
    rolling_utilization = (cost / rolling_window_usd) if rolling_window_usd > 0 else 0.0

    # Rolling-window enterprise/team seats are not API invoices. Interpret
    # estimated token cost as quota pressure. Upgrade only if the user is both
    # high-efficiency and close to the rolling cap; otherwise train/model-route first.
    if is_rolling and rolling_window_usd > 0:
        if rolling_utilization >= 0.85 and overall_score >= 85 and not premium_waste_triggered:
            return {
                "action": "upgrade",
                "plan": "higher_rolling_window",
                "reason": f"High-efficiency user is using {rolling_utilization:.0%} of a ${rolling_window_usd:.0f} rolling window. Consider a higher quota/seat before they hit the cap.",
            }
        if rolling_pressure_triggered or rolling_utilization >= 0.85:
            return {
                "action": "train_first",
                "plan": "maintain",
                "reason": f"Rolling-window pressure detected ({rolling_utilization:.0%} of quota). Improve prompt reuse, skills, and model routing before increasing the window.",
            }
        if requests < 30:
            return {
                "action": "review",
                "plan": "consider_downgrade",
                "reason": "Low usage on a fixed/rolling seat. Consider seat sharing or a lower tier if this continues.",
            }
        return {
            "action": "maintain",
            "plan": "current",
            "reason": f"Rolling-window usage is healthy ({rolling_utilization:.0%} of quota). Maintain current seat and monitor trend.",
        }

    # High usage + high efficiency + high cost -> upgrade
    if requests > 200 and overall_score > 80 and cost > 50:
        return {
            "action": "upgrade",
            "plan": "premium/unlimited",
            "reason": "High-volume, efficient user who would benefit from higher caps and premium model access.",
        }

    # Premium waste firing -> train first, don't upgrade
    if premium_waste_triggered:
        return {
            "action": "train_first",
            "plan": "maintain",
            "reason": "Premium model waste detected. Training will yield more ROI than a plan upgrade — they'll waste the larger budget too.",
        }

    # Model overreliance -> train on model selection first
    if model_overreliance_triggered:
        return {
            "action": "train_first",
            "plan": "maintain",
            "reason": "Model overreliance detected. Teach multi-model workflows before upgrading.",
        }

    # Low usage -> consider downgrade or seat sharing
    if requests < 30:
        return {
            "action": "review",
            "plan": "consider_downgrade",
            "reason": "Very low AI usage. Consider seat sharing or a lower tier.",
        }

    # Good model diversity + auto routing -> maintain
    if overall_score > 70:
        return {
            "action": "maintain",
            "plan": "current",
            "reason": "Good efficiency and model diversity. Maintain current plan.",
        }

    # Default
    return {
        "action": "train_first",
        "plan": "maintain",
        "reason": "Efficiency gaps detected. Address training needs before changing plan tier.",
    }


def recommendations_for_employee(employee_data: dict[str, Any]) -> dict[str, Any]:
    """Convenience: build the full recommendations block for an employee detail."""
    return {
        "training": training_recommendations(employee_data.get("anti_patterns") or []),
        "plan": recommend_plan(employee_data),
    }
