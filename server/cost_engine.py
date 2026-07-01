"""Plan-aware cost engine.

Interprets raw token-estimated costs differently depending on the employee's
billing plan. For seat/rolling-window plans, token cost is quota pressure,
not invoice spend. For API plans, it's direct cost. For hybrid plans, it's
seat cost + API overage.

Also provides plan-fit analysis: is the employee on the right plan for their
usage pattern, and what specific upgrade/downgrade would help?
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

try:
    from plan_catalog import PLAN_CATALOG, get_plan, get_plans_by_provider
    _HAS_CATALOG = True
except ImportError:
    _HAS_CATALOG = False
    PLAN_CATALOG = []

    def get_plan(plan_id: str) -> dict[str, Any] | None:
        return None

    def get_plans_by_provider(provider: str) -> list[dict[str, Any]]:
        return []


# ---------------------------------------------------------------------------
# Cost interpretation
# ---------------------------------------------------------------------------


def _resolve_plan_meta(plan_context: dict[str, Any]) -> tuple[str, dict[str, Any] | None]:
    """Resolve either plan_id or plan_type as a catalog plan ID.

    Early collector configs used ``plan_type`` for billing semantics. Newer
    setup prompts use catalog IDs such as ``claude_team_standard``. Support
    both so plan setup is visible and reliable.
    """
    plan_id = str(plan_context.get("plan_id") or "")
    plan_type = str(plan_context.get("plan_type") or "")
    candidates = [p for p in [plan_id, plan_type] if p]
    if _HAS_CATALOG:
        for candidate in candidates:
            meta = get_plan(candidate)
            if meta:
                return candidate, meta
    return plan_id or plan_type, None


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).date()
    except ValueError:
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None


def billing_months_for_period(summary: dict[str, Any]) -> int:
    """Count calendar months touched by the snapshot period.

    Seat subscriptions are billed by month, not by token volume. If work spans
    Jan→Apr on a $25 seat, spend is 4 × $25 = $100. Missing dates default to one
    billed month when there is any activity/cost, otherwise zero.
    """
    start = _parse_date(summary.get("period_start") or summary.get("start_date"))
    end = _parse_date(summary.get("period_end") or summary.get("end_date") or summary.get("collected_at"))
    if start and end:
        if end < start:
            start, end = end, start
        return max(1, (end.year - start.year) * 12 + (end.month - start.month) + 1)
    has_activity = any(float(summary.get(k, 0) or 0) > 0 for k in ("total_requests", "total_sessions", "estimated_cost_usd"))
    return 1 if has_activity else 0


def interpret_cost(summary: dict[str, Any], plan_context: dict[str, Any]) -> dict[str, Any]:
    """Interpret raw estimated cost based on the employee's billing plan.

    Returns a dict with:
      - display_cost: the cost number to show in dashboards
      - cost_label: what the cost means (e.g. "Quota Pressure", "Estimated Spend")
      - billing_mode: the plan's billing mode
      - utilization: for rolling-window plans, fraction of window used
      - seat_cost: for seat plans, the monthly seat cost
      - api_overage: for hybrid plans, estimated API spend beyond seat
      - remaining_budget: for rolling/credit plans, remaining capacity
      - pressure_level: low / moderate / high / critical
    """
    estimated_cost = float(summary.get("estimated_cost_usd", 0.0) or 0.0)
    total_requests = int(summary.get("total_requests", 0) or 0)
    billed_months = billing_months_for_period(summary)

    plan_id, plan_meta = _resolve_plan_meta(plan_context)
    billing_mode = str(plan_context.get("billing_mode") or plan_context.get("plan_type") or "api").lower()
    rolling_window_usd = float(plan_context.get("rolling_window_usd", 0.0) or 0.0)
    rolling_window_hours = int(plan_context.get("rolling_window_hours", 0) or 0)
    rolling_window_days = int(plan_context.get("rolling_window_days", 0) or 0)
    seat_cost_usd = float(plan_context.get("seat_cost_usd", 0.0) or 0.0)
    included_credits = float(plan_context.get("included_credits", 0.0) or 0.0)
    context_window_tokens = int(plan_context.get("context_window_tokens", 0) or 0)
    max_context_tokens = int(plan_context.get("max_context_tokens", 0) or context_window_tokens or 0)
    total_context_tokens = int(summary.get("total_context_tokens", 0) or 0)
    if not total_context_tokens:
        total_context_tokens = int(summary.get("total_input_tokens", 0) or 0) + int(summary.get("total_output_tokens", 0) or 0)

    # If we have catalog metadata, pull billing mode and seat cost from catalog.
    if plan_meta:
        billing_mode = plan_meta.get("billing_mode", billing_mode)
        if not seat_cost_usd:
            seat_cost_usd = float(plan_meta.get("price_usd", 0) or 0)
        if not rolling_window_days and plan_meta.get("rolling_window_days"):
            rolling_window_days = int(plan_meta["rolling_window_days"])
        if not rolling_window_hours and plan_meta.get("rolling_window_hours"):
            rolling_window_hours = int(plan_meta["rolling_window_hours"])

    result: dict[str, Any] = {
        "billing_mode": billing_mode,
        "seat_cost": seat_cost_usd,
        "utilization": 0.0,
        "remaining_budget": 0.0,
        "pressure_level": "low",
        "api_overage": 0.0,
        "estimated_token_cost": round(estimated_cost, 4),
        "billed_months": billed_months,
        "context_window_tokens": max_context_tokens,
        "context_usage_tokens": total_context_tokens,
        "context_utilization": round(total_context_tokens / max_context_tokens, 4) if max_context_tokens > 0 else 0.0,
    }

    if billing_mode == "api":
        result["display_cost"] = estimated_cost
        result["cost_label"] = "Estimated API Spend"
        result["remaining_budget"] = 0.0
        result["pressure_level"] = _pressure_from_cost(estimated_cost)

    elif billing_mode == "seat_fixed":
        result["display_cost"] = round(seat_cost_usd * billed_months, 2)
        result["cost_label"] = "Billed Seat Spend"
        result["utilization"] = 0.0
        result["pressure_level"] = "low"

    elif billing_mode == "seat_rolling":
        window_budget = rolling_window_usd if rolling_window_usd > 0 else 0
        utilization = (estimated_cost / window_budget) if window_budget > 0 else 0.0
        result["display_cost"] = round(seat_cost_usd * billed_months, 2)
        result["cost_label"] = "Billed Seat Spend"
        result["utilization"] = round(utilization, 4)
        result["remaining_budget"] = round(max(0.0, window_budget - estimated_cost), 2)
        result["pressure_level"] = _pressure_from_utilization(utilization)
        result["window_usd"] = window_budget
        result["window_hours"] = rolling_window_hours
        result["window_days"] = rolling_window_days
        result["usage_label"] = "Rolling Window Pressure"

    elif billing_mode == "seat_credits":
        result["display_cost"] = round(seat_cost_usd * billed_months, 2)
        result["cost_label"] = "Billed Seat Spend"
        if included_credits > 0:
            utilization = estimated_cost / included_credits
            result["utilization"] = round(utilization, 4)
            result["remaining_budget"] = round(max(0.0, included_credits - estimated_cost), 2)
            result["pressure_level"] = _pressure_from_utilization(utilization)
        result["included_credits"] = included_credits
        result["usage_label"] = "Credit Pressure"

    elif billing_mode == "seat_hybrid":
        api_overage = max(0.0, estimated_cost - seat_cost_usd)
        result["display_cost"] = round((seat_cost_usd * billed_months) + api_overage, 2)
        result["cost_label"] = "Seat + API Overage"
        result["api_overage"] = round(api_overage, 2)
        result["pressure_level"] = _pressure_from_cost(api_overage)

    else:
        result["display_cost"] = estimated_cost
        result["cost_label"] = "Estimated Cost"

    return result


def _pressure_from_utilization(utilization: float) -> str:
    if utilization >= 1.0:
        return "critical"
    if utilization >= 0.85:
        return "high"
    if utilization >= 0.5:
        return "moderate"
    return "low"


def _pressure_from_cost(cost: float) -> str:
    if cost > 100:
        return "high"
    if cost > 50:
        return "moderate"
    if cost > 10:
        return "low"
    return "low"


# ---------------------------------------------------------------------------
# Plan fit analysis
# ---------------------------------------------------------------------------


def analyze_plan_fit(summary: dict[str, Any], plan_context: dict[str, Any], overall_score: float = 0.0) -> dict[str, Any]:
    """Analyze whether the employee is on the right plan and suggest changes.

    Returns:
      - current_plan_id
      - recommended_plan_id (or None if no change needed)
      - recommendation: upgrade | downgrade | maintain | train_first
      - reason
      - projected_cost_change
      - alternatives: list of plan_ids that could work
    """
    cost_info = interpret_cost(summary, plan_context)
    billing_mode = cost_info["billing_mode"]
    pressure = cost_info["pressure_level"]
    utilization = cost_info["utilization"]
    total_requests = int(summary.get("total_requests", 0) or 0)

    plan_id, plan_meta = _resolve_plan_meta(plan_context)
    provider = str(plan_context.get("provider") or (plan_meta or {}).get("provider") or "")

    # High pressure on rolling window → upgrade
    if pressure in ("high", "critical") and overall_score >= 80:
        upgrade_target = _find_upgrade_plan(plan_id, provider)
        if upgrade_target:
            new_seat = float(upgrade_target.get("price_usd", 0) or 0)
            current_seat = cost_info.get("seat_cost", 0)
            return {
                "current_plan_id": plan_id,
                "recommended_plan_id": upgrade_target["id"],
                "recommendation": "upgrade",
                "reason": f"User is at {utilization:.0%} of their rolling window with high efficiency. Upgrade to {upgrade_target['name']} ({upgrade_target.get('relative_usage', 'more usage')}) before they hit the cap.",
                "projected_cost_change": round(new_seat - current_seat, 2),
                "alternatives": [p["id"] for p in _find_alternative_plans(plan_id, provider)],
            }

    # High pressure but low efficiency → train first
    if pressure in ("high", "critical") and overall_score < 80:
        return {
            "current_plan_id": plan_id,
            "recommended_plan_id": plan_id,
            "recommendation": "train_first",
            "reason": f"User is at {utilization:.0%} of their rolling window but efficiency is low ({overall_score:.0f}/100). Training will reduce waste before any plan change.",
            "projected_cost_change": 0.0,
            "alternatives": [],
        }

    # Low usage on a paid seat → consider downgrade
    if total_requests < 30 and billing_mode.startswith("seat"):
        downgrade_target = _find_downgrade_plan(plan_id, provider)
        if downgrade_target:
            new_seat = float(downgrade_target.get("price_usd", 0) or 0)
            current_seat = cost_info.get("seat_cost", 0)
            return {
                "current_plan_id": plan_id,
                "recommended_plan_id": downgrade_target["id"],
                "recommendation": "downgrade",
                "reason": f"Very low usage ({total_requests} requests) on a paid seat. Consider {downgrade_target['name']} to save ${round(current_seat - new_seat, 2)}/month.",
                "projected_cost_change": round(new_seat - current_seat, 2),
                "alternatives": [],
            }

    return {
        "current_plan_id": plan_id,
        "recommended_plan_id": plan_id,
        "recommendation": "maintain",
        "reason": f"Plan usage is healthy ({pressure} pressure). Maintain current plan.",
        "projected_cost_change": 0.0,
        "alternatives": [],
    }


def _safe_price(p: dict[str, Any]) -> float:
    """Get price_usd as float, treating None as 0."""
    try:
        return float(p.get("price_usd") or 0)
    except (TypeError, ValueError):
        return 0.0


def _find_upgrade_plan(current_plan_id: str, provider: str) -> dict[str, Any] | None:
    """Find the next plan up from the current one within the same provider."""
    if not _HAS_CATALOG or not provider:
        return None
    plans = get_plans_by_provider(provider)
    # Filter to seat-based plans, sort by price
    seat_plans = [p for p in plans if p.get("billing_mode", "").startswith("seat") and _safe_price(p) > 0]
    seat_plans.sort(key=_safe_price)

    for i, p in enumerate(seat_plans):
        if p["id"] == current_plan_id and i + 1 < len(seat_plans):
            return seat_plans[i + 1]
    # If current plan not found or is already top, return None
    return None


def _find_downgrade_plan(current_plan_id: str, provider: str) -> dict[str, Any] | None:
    """Find the next plan down from the current one within the same provider."""
    if not _HAS_CATALOG or not provider:
        return None
    plans = get_plans_by_provider(provider)
    seat_plans = [p for p in plans if p.get("billing_mode", "").startswith("seat") and _safe_price(p) >= 0]
    seat_plans.sort(key=_safe_price)

    for i, p in enumerate(seat_plans):
        if p["id"] == current_plan_id and i > 0:
            return seat_plans[i - 1]
    return None


def _find_alternative_plans(current_plan_id: str, provider: str) -> list[dict[str, Any]]:
    """Find alternative plans (same provider, different tier) for the user."""
    if not _HAS_CATALOG or not provider:
        return []
    plans = get_plans_by_provider(provider)
    return [p for p in plans if p["id"] != current_plan_id and p.get("billing_mode", "").startswith("seat") and _safe_price(p) > 0]
