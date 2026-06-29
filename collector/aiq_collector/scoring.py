"""
Practice scoring + model tier classification + cost estimation.

Ports the scoring logic from Microsoft's AI-Engineering-Coach ``scoring.ts``
and the model/token constants from ``constants.ts``.

Five practice groups are scored 0–100:
    * prompt-quality
    * session-hygiene
    * code-review
    * tool-mastery
    * context-management

Each group has a per-request penalty function; the score is
``max(0, round(100 - (sum_penalties / total_requests) * 100))``.

Stdlib-only.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any

from .models import Session, SessionRequest

# ---------------------------------------------------------------------------
# Model tier classification  (from AIEC constants.ts MODEL_MULTIPLIERS)
# ---------------------------------------------------------------------------

# Tier 0 — free / basic
TIER_0_MODELS: frozenset[str] = frozenset({
    "gpt-4.1", "gpt-4.1-mini", "gpt-5-mini",
    "claude-haiku-4.5",
    "gemini-2.0-flash", "gemini-3-flash",
    "raptor-mini", "copilot-internal",
})

# Tier 1 — premium
TIER_1_MODELS: frozenset[str] = frozenset({
    "gpt-5.1", "gpt-5.2",
    "claude-sonnet-4", "claude-sonnet-4.5", "claude-sonnet-4.6",
    "claude-3.5-sonnet", "claude-3.7-sonnet",
    "gemini-2.5-pro", "gemini-3-pro",
    "auto", "o1", "o3", "o4-mini",
})

# Tier 3 — ultra-premium
TIER_3_MODELS: frozenset[str] = frozenset({
    "claude-opus-4.5", "claude-opus-4.6",
})

# Tier 7.5 — top-tier opus
TIER_7_5_MODELS: frozenset[str] = frozenset({
    "claude-opus-4.7",
})

# Suffixes to strip when normalizing model IDs
_MODEL_SUFFIX_RE = re.compile(r"(-thought|-preview|-latest|-\d{8}$)", re.IGNORECASE)

# Date suffix like -20260522
_DATE_SUFFIX_RE = re.compile(r"-\d{8}$")


def normalize_model_id(model: str) -> str:
    """Normalize a raw model ID to the canonical form used in tier/rate tables.

    * strip ``copilot/`` prefix
    * strip ``-thought``, ``-preview``, ``-latest``, ``-YYYYMMDD`` suffixes
    * convert ``claude-sonnet-4-6`` → ``claude-sonnet-4.6``
    """
    if not model:
        return ""
    m = model.strip()
    # strip copilot/ prefix
    if m.startswith("copilot/"):
        m = m[len("copilot/"):]
    # strip known suffixes (may match several)
    while True:
        new = _MODEL_SUFFIX_RE.sub("", m)
        if new == m:
            break
        m = new
    # convert claude hyphenated versions: claude-sonnet-4-6 → claude-sonnet-4.6
    # Pattern: claude-(sonnet|opus|haiku)-<major>-<minor>
    m = re.sub(
        r"^(claude-(?:sonnet|opus|haiku)-\d+)-(\d+)$",
        r"\1.\2",
        m,
    )
    return m.lower()


def model_tier(model: str) -> int:
    """Return the pricing tier (0, 1, 3, 7.5) for a model ID.

    Unknown models default to tier 1 (premium).
    """
    norm = normalize_model_id(model)
    if not norm:
        return 1
    if norm in TIER_0_MODELS:
        return 0
    if norm in TIER_3_MODELS:
        return 3
    if norm in TIER_7_5_MODELS:
        return 7
    if norm in TIER_1_MODELS:
        return 1
    # prefix fallbacks — handle versioned variants like claude-sonnet-4-20250514
    if "claude-haiku" in norm:
        return 0
    if "claude-opus-4.7" in norm:
        return 7
    if "claude-opus" in norm:
        return 3
    if "claude-sonnet" in norm or "claude-3" in norm:
        return 1
    if "gemini-flash" in norm or "gemini-2.0" in norm or "gemini-3-flash" in norm:
        return 0
    if "gemini" in norm and "pro" in norm:
        return 1
    if "gpt-5-mini" in norm or "gpt-4.1-mini" in norm or "gpt-4.1" in norm:
        return 0
    if "gpt-5" in norm or "o1" == norm or "o3" == norm or "o4-mini" == norm:
        return 1
    if "raptor" in norm or "copilot-internal" in norm:
        return 0
    return 1


# ---------------------------------------------------------------------------
# Token rates (USD per 1M tokens, from AIEC constants.ts)
# ---------------------------------------------------------------------------

TOKEN_RATES: dict[str, dict[str, float]] = {
    "claude-sonnet-4.6": {"input": 3.00, "cached": 0.30, "output": 15.00, "cacheWrite": 3.75},
    "claude-sonnet-4.5": {"input": 3.00, "cached": 0.30, "output": 15.00, "cacheWrite": 3.75},
    "claude-sonnet-4":   {"input": 3.00, "cached": 0.30, "output": 15.00, "cacheWrite": 3.75},
    "claude-opus-4.5":   {"input": 5.00, "cached": 0.50, "output": 25.00, "cacheWrite": 6.25},
    "claude-opus-4.6":   {"input": 5.00, "cached": 0.50, "output": 25.00, "cacheWrite": 6.25},
    "claude-opus-4.7":   {"input": 5.00, "cached": 0.50, "output": 25.00, "cacheWrite": 6.25},
    "claude-haiku-4.5":  {"input": 1.00, "cached": 0.10, "output": 5.00, "cacheWrite": 1.25},
    # GPT-5.x — no cacheWrite key (uses cached rate for cache writes)
    "gpt-5.1":           {"input": 1.75, "cached": 0.175, "output": 14.00},
    "gpt-5.2":           {"input": 1.75, "cached": 0.175, "output": 14.00},
}

# Default rate for unknown models — assume mid-range Claude Sonnet pricing
_DEFAULT_RATE: dict[str, float] = {"input": 3.00, "cached": 0.30, "output": 15.00, "cacheWrite": 3.75}


def _get_rate(model: str) -> dict[str, float]:
    """Look up the token-rate table for a model (normalized)."""
    norm = normalize_model_id(model)
    if norm in TOKEN_RATES:
        return TOKEN_RATES[norm]
    # prefix fallback
    if "claude-opus-4.7" in norm:
        return TOKEN_RATES["claude-opus-4.7"]
    if "claude-opus" in norm:
        return TOKEN_RATES["claude-opus-4.6"]
    if "claude-sonnet" in norm:
        return TOKEN_RATES["claude-sonnet-4.6"]
    if "claude-haiku" in norm:
        return TOKEN_RATES["claude-haiku-4.5"]
    if "gpt-5.1" in norm:
        return TOKEN_RATES["gpt-5.1"]
    if "gpt-5.2" in norm:
        return TOKEN_RATES["gpt-5.2"]
    return _DEFAULT_RATE


def estimate_request_cost(req: SessionRequest) -> float:
    """Estimate USD cost for a single request across all models it used.

    If a request used multiple models, tokens are attributed to the first
    (primary) model — consistent with how AIEC attributes per-turn cost.
    """
    model = req.model
    if not model or model == "<synthetic>":
        return 0.0
    rate = _get_rate(model)
    # input = base input + cache read (at cached rate) + cache write (at cacheWrite rate)
    base_input = req.input_tokens - req.cache_read_tokens - req.cache_write_tokens
    if base_input < 0:
        base_input = 0
    cost = (
        (base_input / 1_000_000) * rate["input"]
        + (req.cache_read_tokens / 1_000_000) * rate["cached"]
        + (req.output_tokens / 1_000_000) * rate["output"]
    )
    # cache write cost — use cacheWrite rate if available, else cached rate
    cw_rate = rate.get("cacheWrite", rate["cached"])
    cost += (req.cache_write_tokens / 1_000_000) * cw_rate
    return round(cost, 6)


# ---------------------------------------------------------------------------
# Practice scores
# ---------------------------------------------------------------------------

PRACTICE_GROUPS: tuple[str, ...] = (
    "prompt-quality",
    "session-hygiene",
    "code-review",
    "tool-mastery",
    "context-management",
)


def _file_refs(req: SessionRequest) -> bool:
    """True if the request references or edits any file."""
    if req.referenced_files or req.edited_files:
        return True
    if re.search(r"[\w/\\]+\.\w{1,5}\b", req.message):
        return True
    return False


def _prompt_quality_penalty(req: SessionRequest) -> float:
    """+1 if messageLength < 30 and > 0; +0.5 if no file refs and no edited files."""
    p = 0.0
    if 0 < req.message_length < 30:
        p += 1.0
    if not _file_refs(req) and not req.edited_files:
        p += 0.5
    return p


def _session_hygiene_penalty(req: SessionRequest) -> float:
    """+1 if canceled; +0.3 if hour < 5; +0.2 if weekend."""
    p = 0.0
    if req.is_canceled:
        p += 1.0
    if req.timestamp_dt:
        if req.timestamp_dt.hour < 5:
            p += 0.3
        if req.timestamp_dt.weekday() >= 5:
            p += 0.2
    return p


def _code_review_penalty(req: SessionRequest) -> float:
    """+0.5 if aiCode present and totalElapsed < 5000ms."""
    p = 0.0
    if req.ai_loc > 0 and 0 < req.elapsed_ms < 5000:
        p += 0.5
    return p


def _tool_mastery_penalty(req: SessionRequest) -> float:
    """+0.3 if no tools used and no slash command."""
    p = 0.0
    has_slash = req.message.strip().startswith("/")
    if req.tool_count == 0 and not has_slash:
        p += 0.3
    return p


def _context_management_penalty(req: SessionRequest) -> float:
    """+1 per missing context-engineering signal (proxy from
    context-engineering-gaps rule)."""
    gaps = 0
    if not req.has_subagents:
        gaps += 1
    if not req.has_skills:
        gaps += 1
    if not req.has_mcp:
        gaps += 1
    if not _file_refs(req):
        gaps += 1
    if not re.search(r"\b(must|should|ensure|need to|require|please|make sure)\b",
                     req.message, re.IGNORECASE):
        gaps += 1
    return float(gaps)


_PENALTY_FUNCS = {
    "prompt-quality": _prompt_quality_penalty,
    "session-hygiene": _session_hygiene_penalty,
    "code-review": _code_review_penalty,
    "tool-mastery": _tool_mastery_penalty,
    "context-management": _context_management_penalty,
}


def _compute_score(penalties: list[float], total: int) -> int:
    """Score = max(0, round(100 - (sum_penalties / total) * 100))."""
    if total == 0:
        return 100
    ratio = sum(penalties) / total
    return max(0, round(100 - ratio * 100))


def _iso_week(dt: datetime) -> str:
    """Return ISO week string like ``2026-W25``."""
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def compute_practice_scores(sessions: list[Session]) -> dict[str, dict[str, Any]]:
    """Compute practice scores (0–100) for all 5 groups plus weekly trends.

    Returns a dict keyed by group name::

        {
          "prompt-quality": {
            "score": 78,
            "weekly": [{"week": "2026-W25", "score": 80}, ...]
          },
          ...
        }
    """
    all_reqs: list[SessionRequest] = []
    for s in sessions:
        all_reqs.extend(s.requests)

    total = len(all_reqs)
    result: dict[str, dict[str, Any]] = {}

    for group in PRACTICE_GROUPS:
        fn = _PENALTY_FUNCS[group]
        penalties = [fn(r) for r in all_reqs]
        score = _compute_score(penalties, total)

        # weekly trend
        weekly_penalties: dict[str, list[float]] = defaultdict(list)
        weekly_totals: dict[str, int] = defaultdict(int)
        for r in all_reqs:
            if not r.timestamp_dt:
                continue
            wk = _iso_week(r.timestamp_dt)
            weekly_penalties[wk].append(fn(r))
            weekly_totals[wk] += 1
        weekly = []
        for wk in sorted(weekly_penalties.keys()):
            wk_total = weekly_totals[wk]
            wk_score = _compute_score(weekly_penalties[wk], wk_total)
            weekly.append({"week": wk, "score": wk_score})

        result[group] = {"score": score, "weekly": weekly}

    return result


# ---------------------------------------------------------------------------
# Model usage aggregation
# ---------------------------------------------------------------------------


def aggregate_model_usage(sessions: list[Session]) -> dict[str, dict[str, Any]]:
    """Aggregate per-model request counts, tokens, and estimated cost."""
    usage: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
    )
    for s in sessions:
        for r in s.requests:
            model = r.model
            if not model or model == "<synthetic>":
                continue
            norm = normalize_model_id(model)
            entry = usage[norm]
            entry["requests"] += 1
            entry["input_tokens"] += r.input_tokens
            entry["output_tokens"] += r.output_tokens
            entry["cost_usd"] = round(entry["cost_usd"] + estimate_request_cost(r), 6)
    # round final costs
    for v in usage.values():
        v["cost_usd"] = round(v["cost_usd"], 4)
    return dict(usage)
