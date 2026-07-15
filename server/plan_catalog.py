"""Structured catalog of AI provider subscription plans.

This module is a pure-data catalog (no DB / no FastAPI dependency) describing
every subscription plan offered by the AI coding assistants that AIQ tracks:
Claude (Anthropic), Codex (OpenAI / ChatGPT), GitHub Copilot, and the generic
"OpenCode / custom" buckets.

The catalog is served by the API so the frontend can render provider/plan
dropdowns without hard-coding pricing. All pricing figures below are verified
as of 2026-06-29 and must NOT be invented or changed without re-verification.

Typical usage::

    from plan_catalog import PLAN_CATALOG, get_plan, get_plans_by_provider

    # Frontend dropdown
    plans = get_plans_by_provider("claude")

    # Cost estimator lookup
    plan = get_plan("claude_pro")
    monthly_cost = plan["price_usd"]

See the ENDPOINT STUB section at the bottom of this module for an example of
how the FastAPI app wires the catalog into ``/api/plans`` routes.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Billing-mode descriptions (shared across all providers)
# ---------------------------------------------------------------------------

BILLING_MODE_DESCRIPTIONS: dict[str, str] = {
    "api": (
        "Pay-per-token API usage. Cost scales directly with input/output/cached "
        "token volume per model. No seat fee."
    ),
    "seat_fixed": (
        "Fixed monthly seat price with a hard usage quota. No overage charges; "
        "usage is capped when the quota is reached."
    ),
    "seat_credits": (
        "Monthly seat price bundled with a credit allowance. Credits are consumed "
        "by model usage (premium models cost more credits per token). Unused "
        "credits may or may not roll over depending on the plan."
    ),
    "seat_rolling": (
        "Monthly seat price with a rolling usage window rather than a fixed "
        "monthly quota. Usage ages out over the window so there is no hard "
        "monthly reset, but throughput is bounded by the window size."
    ),
    "seat_hybrid": (
        "Combines a per-seat base fee with metered API-style usage. Seat fee "
        "covers an allowance; consumption beyond it is billed per-token."
    ),
}


# ---------------------------------------------------------------------------
# Plan catalog
# ---------------------------------------------------------------------------

PLAN_CATALOG: list[dict[str, Any]] = [
    # =======================================================================
    # Claude (Anthropic)
    # =======================================================================
    {
        "id": "claude_free",
        "provider": "claude",
        "name": "Claude Free",
        "billing_mode": "seat_fixed",
        "price_usd": 0,
        "price_note": "Free",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "1x (base)",
        "seat_type": "individual",
        "features": [
            "Claude.ai chat",
            "Limited daily usage",
        ],
        "recommended_for": "Light, occasional use",
    },
    {
        "id": "claude_pro",
        "provider": "claude",
        "name": "Claude Pro",
        "billing_mode": "seat_rolling",
        "price_usd": 20,
        "price_note": "$17/mo annual, $20/mo monthly",
        "rolling_window_hours": None,
        "rolling_window_days": 30,
        "relative_usage": "5x Free",
        "seat_type": "individual",
        "features": [
            "Claude Code",
            "Claude Cowork",
            "Higher usage limits",
            "Priority access during peaks",
        ],
        "recommended_for": "Everyday productivity",
    },
    {
        "id": "claude_max_5x",
        "provider": "claude",
        "name": "Claude Max 5x",
        "billing_mode": "seat_rolling",
        "price_usd": 100,
        "price_note": "$100/mo",
        "rolling_window_hours": None,
        "rolling_window_days": 30,
        "relative_usage": "5x Pro",
        "seat_type": "individual",
        "features": [
            "5x Pro usage",
            "Claude Code (high volume)",
            "Early feature access",
        ],
        "recommended_for": "Power users and heavy Claude Code usage",
    },
    {
        "id": "claude_max_20x",
        "provider": "claude",
        "name": "Claude Max 20x",
        "billing_mode": "seat_rolling",
        "price_usd": 200,
        "price_note": "$200/mo",
        "rolling_window_hours": None,
        "rolling_window_days": 30,
        "relative_usage": "20x Pro",
        "seat_type": "individual",
        "features": [
            "20x Pro usage",
            "Claude Code (very high volume)",
            "Highest priority access",
        ],
        "recommended_for": "All-day, every-day Claude Code workflows",
    },
    {
        "id": "claude_team_standard",
        "provider": "claude",
        "name": "Claude Team Standard",
        "billing_mode": "seat_rolling",
        "price_usd": 25,
        "price_note": "$20/seat/mo annual, $25/seat/mo monthly",
        "rolling_window_hours": None,
        "rolling_window_days": 30,
        "relative_usage": "~Pro per seat",
        "seat_type": "team",
        "features": [
            "Shared workspace",
            "Admin console",
            "Centralized billing",
        ],
        "recommended_for": "Small-to-mid teams wanting shared access",
    },
    {
        "id": "claude_team_premium",
        "provider": "claude",
        "name": "Claude Team Premium",
        "billing_mode": "seat_rolling",
        "price_usd": 125,
        "price_note": "$100/seat/mo annual, $125/seat/mo monthly",
        "rolling_window_hours": None,
        "rolling_window_days": 30,
        "relative_usage": "~Max 5x per seat",
        "seat_type": "team",
        "features": [
            "Higher per-seat usage",
            "Shared workspace",
            "Admin console",
            "Centralized billing",
        ],
        "recommended_for": "Teams with heavy per-seat usage",
    },
    {
        "id": "claude_enterprise",
        "provider": "claude",
        "name": "Claude Enterprise",
        "billing_mode": "seat_hybrid",
        "price_usd": None,
        "price_note": "$20/seat base + API usage (contact sales)",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "Custom",
        "seat_type": "enterprise",
        "features": [
            "SSO / SAML",
            "SCIM provisioning",
            "Audit logs",
            "Custom retention",
            "Volume API pricing",
        ],
        "recommended_for": "Large organizations with security/compliance needs",
    },
    {
        "id": "claude_api",
        "provider": "claude",
        "name": "Claude API (per-token)",
        "billing_mode": "api",
        "price_usd": None,
        "price_note": (
            "Per MTok input/output: Fable 5 $10/$50, Opus 4.8 $5/$25, "
            "Sonnet 4.6 $3/$15, Haiku 4.5 $1/$5"
        ),
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "Metered",
        "seat_type": "individual",
        "features": [
            "Direct API access",
            "Pay-per-token",
            "Model selection (Fable 5, Opus 4.8, Sonnet 4.6, Haiku 4.5)",
        ],
        "recommended_for": "Programmatic / embedded usage, cost-optimization",
        "api_pricing": {
            # USD per 1M (MTok) tokens, input / output
            "fable_5": {"input": 10.0, "output": 50.0},
            "opus_4_8": {"input": 5.0, "output": 25.0},
            "sonnet_4_6": {"input": 3.0, "output": 15.0},
            "haiku_4_5": {"input": 1.0, "output": 5.0},
        },
    },

    # =======================================================================
    # OpenAI Codex (ChatGPT plans)
    # =======================================================================
    {
        "id": "codex_free",
        "provider": "codex",
        "name": "ChatGPT Free (Codex)",
        "billing_mode": "seat_rolling",
        "price_usd": 0,
        "price_note": "Free",
        "rolling_window_hours": 5,
        "rolling_window_days": None,
        "relative_usage": "1x (base)",
        "seat_type": "individual",
        "features": [
            "ChatGPT Free",
            "Limited Codex usage",
            "5-hour rolling window",
        ],
        "recommended_for": "Trying Codex / light use",
    },
    {
        "id": "codex_go",
        "provider": "codex",
        "name": "ChatGPT Go (Codex)",
        "billing_mode": "seat_rolling",
        "price_usd": 8,
        "price_note": "$8/mo",
        "rolling_window_hours": 5,
        "rolling_window_days": None,
        "relative_usage": "Higher than Free",
        "seat_type": "individual",
        "features": [
            "ChatGPT Go",
            "Codex access",
            "5-hour rolling window",
        ],
        "recommended_for": "Casual Codex users",
    },
    {
        "id": "codex_plus",
        "provider": "codex",
        "name": "ChatGPT Plus (Codex)",
        "billing_mode": "seat_rolling",
        "price_usd": 20,
        "price_note": "$20/mo",
        "rolling_window_hours": 5,
        "rolling_window_days": None,
        "relative_usage": "Standard",
        "seat_type": "individual",
        "features": [
            "ChatGPT Plus",
            "Codex CLI / IDE access",
            "5-hour rolling window",
            "Higher message limits",
        ],
        "recommended_for": "Regular Codex users",
    },
    {
        "id": "codex_pro_5x",
        "provider": "codex",
        "name": "ChatGPT Pro 5x (Codex)",
        "billing_mode": "seat_rolling",
        "price_usd": 100,
        "price_note": "$100/mo",
        "rolling_window_hours": 5,
        "rolling_window_days": None,
        "relative_usage": "5x Plus",
        "seat_type": "individual",
        "features": [
            "5x Plus message limits",
            "Codex (high volume)",
            "5-hour rolling window",
        ],
        "recommended_for": "Heavy Codex users",
    },
    {
        "id": "codex_pro_20x",
        "provider": "codex",
        "name": "ChatGPT Pro 20x (Codex)",
        "billing_mode": "seat_rolling",
        "price_usd": 200,
        "price_note": "$200/mo",
        "rolling_window_hours": 5,
        "rolling_window_days": None,
        "relative_usage": "20x Plus",
        "seat_type": "individual",
        "features": [
            "20x Plus message limits",
            "Codex (very high volume)",
            "5-hour rolling window",
        ],
        "recommended_for": "All-day Codex workflows",
    },
    {
        "id": "codex_business",
        "provider": "codex",
        "name": "ChatGPT Business (Codex)",
        "billing_mode": "seat_credits",
        "price_usd": None,
        "price_note": "Contact sales",
        "rolling_window_hours": 5,
        "rolling_window_days": None,
        "relative_usage": "Custom",
        "seat_type": "team",
        "features": [
            "Team admin console",
            "Centralized billing",
            "Pooled / seat credits",
        ],
        "recommended_for": "Small-to-mid teams",
    },
    {
        "id": "codex_enterprise",
        "provider": "codex",
        "name": "ChatGPT Enterprise / Edu (Codex)",
        "billing_mode": "seat_credits",
        "price_usd": None,
        "price_note": "Contact sales",
        "rolling_window_hours": 5,
        "rolling_window_days": None,
        "relative_usage": "Custom",
        "seat_type": "enterprise",
        "features": [
            "SSO / SAML",
            "SCIM provisioning",
            "Audit logs",
            "Custom retention",
        ],
        "recommended_for": "Large organizations / educational institutions",
    },
    {
        "id": "codex_api",
        "provider": "codex",
        "name": "OpenAI API Key (Codex)",
        "billing_mode": "api",
        "price_usd": None,
        "price_note": (
            "Per 1M tokens input/cached/output: GPT-5.5 125/12.50/750, "
            "GPT-5.4 62.50/6.25/375, GPT-5.4 mini 18.75/1.875/113"
        ),
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "Metered",
        "seat_type": "individual",
        "features": [
            "Direct API access",
            "Pay-per-token",
            "Model selection (GPT-5.5, GPT-5.4, GPT-5.4 mini)",
            "Cached input discount",
        ],
        "recommended_for": "Programmatic / embedded usage, cost-optimization",
        "api_pricing": {
            # USD per 1M tokens, input / cached_input / output
            "gpt_5_5": {"input": 125.0, "cached_input": 12.50, "output": 750.0},
            "gpt_5_4": {"input": 62.50, "cached_input": 6.25, "output": 375.0},
            "gpt_5_4_mini": {"input": 18.75, "cached_input": 1.875, "output": 113.0},
        },
    },

    # =======================================================================
    # GitHub Copilot
    # =======================================================================
    {
        "id": "copilot_free",
        "provider": "copilot",
        "name": "Copilot Free",
        "billing_mode": "seat_fixed",
        "price_usd": 0,
        "price_note": "Free (2000 completions/mo)",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "1x (base)",
        "seat_type": "individual",
        "features": [
            "2000 completions/mo",
            "Copilot Chat (limited)",
            "Limited premium requests",
        ],
        "recommended_for": "Trying Copilot / light use",
    },
    {
        "id": "copilot_pro",
        "provider": "copilot",
        "name": "Copilot Pro",
        "billing_mode": "seat_credits",
        "price_usd": 10,
        "price_note": "$10/mo ($15 monthly premium-request credits)",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "Standard",
        "seat_type": "individual",
        "features": [
            "Unlimited completions",
            "Copilot Chat",
            "$15/mo premium-request credits",
        ],
        "recommended_for": "Individual developers",
    },
    {
        "id": "copilot_pro_plus",
        "provider": "copilot",
        "name": "Copilot Pro+",
        "billing_mode": "seat_credits",
        "price_usd": 39,
        "price_note": "$39/mo ($70 monthly premium-request credits)",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "~2x Pro credits",
        "seat_type": "individual",
        "features": [
            "Unlimited completions",
            "Copilot Chat",
            "$70/mo premium-request credits",
            "Additional premium models",
        ],
        "recommended_for": "Heavy premium-model users",
    },
    {
        "id": "copilot_max",
        "provider": "copilot",
        "name": "Copilot Max",
        "billing_mode": "seat_credits",
        "price_usd": 100,
        "price_note": "$100/mo ($200 monthly premium-request credits)",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "~2x Pro+ credits",
        "seat_type": "individual",
        "features": [
            "Unlimited completions",
            "Copilot Chat",
            "$200/mo premium-request credits",
            "All premium models",
        ],
        "recommended_for": "Max premium-model throughput",
    },
    {
        "id": "copilot_business",
        "provider": "copilot",
        "name": "Copilot Business",
        "billing_mode": "seat_credits",
        "price_usd": 19,
        "price_note": "$19/seat/mo (pooled credits)",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "Business tier",
        "seat_type": "team",
        "features": [
            "Unlimited completions",
            "Copilot Chat",
            "Pooled premium-request credits",
            "Admin policy controls",
        ],
        "recommended_for": "Teams wanting pooled credit flexibility",
    },
    {
        "id": "copilot_enterprise",
        "provider": "copilot",
        "name": "Copilot Enterprise",
        "billing_mode": "seat_credits",
        "price_usd": 39,
        "price_note": "$39/seat/mo (2x Business credits)",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "2x Business",
        "seat_type": "enterprise",
        "features": [
            "All Business features",
            "2x pooled credits per seat",
            "Custom knowledge base indexing",
            "Enterprise security & compliance",
        ],
        "recommended_for": "Large organizations with custom KB / compliance",
    },

    # =======================================================================
    # OpenCode / Other (generic)
    # =======================================================================
    {
        "id": "opencode_custom",
        "provider": "opencode",
        "name": "OpenCode Custom Plan",
        "billing_mode": "seat_credits",
        "price_usd": None,
        "price_note": "User-defined",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "Custom",
        "seat_type": "individual",
        "features": [
            "User-defined plan",
            "Custom seat / credit allocation",
        ],
        "recommended_for": "Bringing your own plan / self-hosted setups",
    },
    {
        "id": "opencode_api",
        "provider": "opencode",
        "name": "OpenCode API (per-token)",
        "billing_mode": "api",
        "price_usd": None,
        "price_note": "User-defined per-token rates",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "Metered",
        "seat_type": "individual",
        "features": [
            "Direct API access",
            "Pay-per-token",
            "User-defined model pricing",
        ],
        "recommended_for": "Custom / Bring-Your-Own-Key setups",
    },
    {
        "id": "custom_custom",
        "provider": "custom",
        "name": "Custom (user-defined)",
        "billing_mode": "seat_credits",
        "price_usd": None,
        "price_note": "User-defined",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "Custom",
        "seat_type": "individual",
        "features": [
            "Fully user-defined",
            "Any provider / billing mode",
        ],
        "recommended_for": "Plans not covered by the built-in catalog",
    },
    {
        "id": "custom_api",
        "provider": "custom",
        "name": "Custom API (per-token)",
        "billing_mode": "api",
        "price_usd": None,
        "price_note": "User-defined per-token rates",
        "rolling_window_hours": None,
        "rolling_window_days": None,
        "relative_usage": "Metered",
        "seat_type": "individual",
        "features": [
            "Direct API access",
            "Pay-per-token",
            "User-defined model pricing",
        ],
        "recommended_for": "Bring-Your-Own-Key for any provider",
    },
]


# ---------------------------------------------------------------------------
# Index for O(1) id lookup
# ---------------------------------------------------------------------------

_PLAN_BY_ID: dict[str, dict[str, Any]] = {p["id"]: p for p in PLAN_CATALOG}

# Stable ordering for provider dropdowns (insertion order preserved).
_PROVIDER_ORDER: list[str] = []
for _p in PLAN_CATALOG:
    if _p["provider"] not in _PROVIDER_ORDER:
        _PROVIDER_ORDER.append(_p["provider"])


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_plan(plan_id: str) -> dict[str, Any] | None:
    """Return the plan dict for ``plan_id`` or ``None`` if not found."""
    return _PLAN_BY_ID.get(plan_id)


def get_plans_by_provider(provider: str) -> list[dict[str, Any]]:
    """Return all plans for a given provider (case-insensitive).

    Accepts either a provider id string (e.g. ``"claude"``) or a dict
    from :func:`get_all_providers` (e.g. ``{"provider": "claude", ...}``).

    Returns an empty list if the provider is unknown.
    """
    if isinstance(provider, dict):
        provider = provider.get("provider", "")
    provider_l = provider.lower()
    return [p for p in PLAN_CATALOG if p["provider"] == provider_l]


def get_all_providers() -> list[dict[str, str]]:
    """Return a stable, ordered list of supported providers.

    Each entry is ``{"provider": <id>, "label": <display name>}`` so the
    frontend can render a provider dropdown without extra metadata.
    """
    labels = {
        "claude": "Claude (Anthropic)",
        "codex": "Codex (OpenAI / ChatGPT)",
        "copilot": "GitHub Copilot",
        "opencode": "OpenCode / Other",
        "custom": "Custom",
    }
    return [
        {"provider": pid, "label": labels.get(pid, pid.title())}
        for pid in _PROVIDER_ORDER
    ]


def get_plans_by_billing_mode(mode: str) -> list[dict[str, Any]]:
    """Return all plans matching a given billing mode (case-insensitive)."""
    mode_l = mode.lower()
    return [p for p in PLAN_CATALOG if p["billing_mode"] == mode_l]


def get_plan_ids() -> list[str]:
    """Return all plan ids in catalog order."""
    return [p["id"] for p in PLAN_CATALOG]


# ---------------------------------------------------------------------------
# Module self-check (cheap sanity assertions, runs on import only in dev/test)
# ---------------------------------------------------------------------------

def _self_check() -> None:
    """Validate catalog integrity: unique ids, valid enums, price consistency."""
    valid_providers = {"claude", "codex", "copilot", "opencode", "custom"}
    valid_modes = set(BILLING_MODE_DESCRIPTIONS.keys())

    ids = [p["id"] for p in PLAN_CATALOG]
    dupes = [i for i in ids if ids.count(i) > 1]
    if dupes:
        raise ValueError(f"Duplicate plan ids in catalog: {sorted(set(dupes))}")

    for p in PLAN_CATALOG:
        if p["provider"] not in valid_providers:
            raise ValueError(
                f"Plan {p['id']} has unknown provider: {p['provider']!r}"
            )
        if p["billing_mode"] not in valid_modes:
            raise ValueError(
                f"Plan {p['id']} has unknown billing_mode: {p['billing_mode']!r}"
            )
        if "rolling_window_hours" not in p or "rolling_window_days" not in p:
            raise ValueError(f"Plan {p['id']} missing rolling-window fields")


# Run integrity check at import time so catalog errors surface immediately.
_self_check()


# ---------------------------------------------------------------------------
# ENDPOINT STUB — example FastAPI wiring for /api/plans
#
# Drop this router into main.py (or a plans.py router module) to serve the
# catalog. It is intentionally commented out so importing this module stays
# side-effect-free with respect to FastAPI.
#
#   from fastapi import APIRouter, HTTPException
#   from plan_catalog import (
#       PLAN_CATALOG,
#       BILLING_MODE_DESCRIPTIONS,
#       get_all_providers,
#       get_plan,
#       get_plans_by_provider,
#   )
#
#   router = APIRouter(prefix="/api/plans", tags=["plans"])
#
#   @router.get("/")
#   def list_plans(provider: str | None = None):
#       # GET /api/plans?provider=claude  -> filtered list
#       if provider:
#           return get_plans_by_provider(provider)
#       return PLAN_CATALOG
#
#   @router.get("/providers")
#   def list_providers():
#       return get_all_providers()
#
#   @router.get("/billing-modes")
#   def list_billing_modes():
#       return BILLING_MODE_DESCRIPTIONS
#
#   @router.get("/{plan_id}")
#   def fetch_plan(plan_id: str):
#       plan = get_plan(plan_id)
#       if plan is None:
#           raise HTTPException(status_code=404, detail=f"Unknown plan id: {plan_id}")
#       return plan
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    # Quick CLI dump for manual inspection.
    import json

    print(f"Total plans: {len(PLAN_CATALOG)}")
    print(f"Providers: {[p['provider'] for p in get_all_providers()]}")
    print()
    for provider in get_all_providers():
        print(f"== {provider['label']} ({provider['provider']}) ==")
        for plan in get_plans_by_provider(provider["provider"]):
            price = plan["price_usd"]
            price_str = f"${price}/mo" if isinstance(price, (int, float)) else "contact/user-defined"
            print(
                f"  {plan['id']:<26} {plan['name']:<34} "
                f"{plan['billing_mode']:<14} {price_str}"
            )
        print()
    print("Billing modes:")
    for mode, desc in BILLING_MODE_DESCRIPTIONS.items():
        print(f"  {mode:<14} {desc[:60]}...")
    print()
    print("Sample lookup (claude_pro):")
    print(json.dumps(get_plan("claude_pro"), indent=2))
