"""Static metadata for all anti-pattern rules.

This module hardcodes the metadata (id, name, group, severity, description,
suggestion, training) for all 20 anti-pattern rules that the collector can
detect. The dashboard uses this to render human-readable rule descriptions
and to map triggered rules to training tracks.

The ``group`` field uses AIQ practice groups, not Microsoft's defaults.
Rules also carry an audit verdict:
  keep = useful signal, watch = useful but noisy proxy, off = weak/intrusive by default.

The ``training`` field maps each rule to a training track + module + priority.
"""

from __future__ import annotations

# Each entry: id, name, group, severity, description, suggestion, training.
RULES_META: list[dict] = [
    # --- Prompt Quality ---
    {
        "id": "lazy-prompting",
        "name": "Lazy Prompting",
        "group": "prompt-quality",
        "severity": "medium",
        "description": "Very short, low-context prompts that force the model to guess intent, producing low-quality or off-target output.",
        "suggestion": "Add explicit context, constraints, and desired output format to every prompt.",
        "training": {"track": "Prompt Engineering", "module": "Writing Effective Prompts", "priority": "high"},
    },
    {
        "id": "repeated-prompts",
        "name": "Repeated Prompts",
        "group": "prompt-quality",
        "severity": "medium",
        "description": "The same or near-duplicate prompt is sent multiple times, indicating a lack of iterative refinement.",
        "suggestion": "Build on previous responses iteratively instead of re-issuing the same prompt.",
        "training": {"track": "Prompt Engineering", "module": "Iterative Prompting Techniques", "priority": "medium"},
    },
    {
        "id": "no-spec-driven-development",
        "name": "No Spec-Driven Development",
        "group": "prompt-quality",
        "severity": "medium",
        "description": "Work is performed without a written spec or task definition, leading to scope creep and rework.",
        "suggestion": "Define a short spec or task description before starting AI-assisted work.",
        "training": {"track": "Prompt Engineering", "module": "Spec-Driven Development", "priority": "high"},
    },
    {
        "id": "verbose-prompt-no-compression",
        "name": "Verbose Prompt Without Compression",
        "group": "prompt-quality",
        "severity": "medium",
        "description": "Prompts are excessively long without using context compression, file references, or skills.",
        "suggestion": "Use file references, skills, and context compression to keep prompts concise.",
        "training": {"track": "Prompt Engineering", "module": "Prompt Compression & Context", "priority": "medium"},
    },
    {
        "id": "no-plan-mode",
        "name": "No Plan Mode Usage",
        "group": "prompt-quality",
        "severity": "low",
        "description": "Plan mode is never used for complex tasks, missing an opportunity to align before execution.",
        "suggestion": "Use plan mode for multi-step or ambiguous tasks to align before executing.",
        "training": {"track": "Prompt Engineering", "module": "Using Plan Mode Effectively", "priority": "low"},
    },
    {
        "id": "no-skills",
        "name": "No Reusable Skills",
        "group": "prompt-quality",
        "severity": "low",
        "description": "No reusable skills are created or used, leading to repeated manual context entry.",
        "suggestion": "Create reusable skills for repeated workflows to encode best practices.",
        "training": {"track": "Prompt Engineering", "module": "Creating Reusable Skills", "priority": "medium"},
    },
    # --- Code Review ---
    {
        "id": "speed-accept",
        "name": "Speed Accept (No Review)",
        "group": "code-review",
        "severity": "high",
        "description": "AI-generated code is accepted within a very short window, indicating insufficient human review.",
        "suggestion": "Review generated code carefully before accepting; verify logic, security, and tests.",
        "training": {"track": "AI Code Review", "module": "Reviewing AI-Generated Code", "priority": "high"},
    },
    {
        "id": "copy-paste-blindness",
        "name": "Copy-Paste Blindness",
        "group": "code-review",
        "severity": "medium",
        "description": "Large blocks of AI output are pasted without modification or review, propagating errors.",
        "suggestion": "Validate generated code in context; never paste blindly.",
        "training": {"track": "AI Code Review", "module": "Validating Generated Code", "priority": "high"},
    },
    # --- Tool Mastery ---
    {
        "id": "premium-waste",
        "name": "Premium Model Waste",
        "group": "tool-mastery",
        "severity": "medium",
        "description": "Premium/expensive models are used for trivial tasks that a cheaper model could handle.",
        "suggestion": "Route simple tasks to cheaper models; reserve premium models for hard problems.",
        "training": {"track": "Model & Tool Selection", "module": "Cost-Aware Model Routing", "priority": "high"},
    },
    {
        "id": "premium-for-lookup-questions",
        "name": "Premium For Lookup Questions",
        "group": "tool-mastery",
        "severity": "medium",
        "description": "Premium models are used for simple factual/lookup questions that a base model can answer.",
        "suggestion": "Use a cheaper model or tool for lookup-style questions.",
        "training": {"track": "Model & Tool Selection", "module": "Choosing the Right Model", "priority": "medium"},
    },
    {
        "id": "model-overreliance",
        "name": "Model Overreliance",
        "group": "tool-mastery",
        "severity": "medium",
        "description": "A single model is used for nearly all requests, missing the benefits of multi-model workflows.",
        "suggestion": "Diversify model usage; match model capability to task difficulty.",
        "training": {"track": "Model & Tool Selection", "module": "Multi-Model Workflows", "priority": "medium"},
    },
    # --- Session Hygiene ---
    {
        "id": "runaway-agent-loops",
        "name": "Runaway Agent Loops",
        "group": "session-hygiene",
        "severity": "high",
        "description": "Agent requests use an excessive number of tools, indicating the agent may be spinning on failing approaches.",
        "suggestion": "Break complex tasks into smaller, focused requests. If the agent is looping, cancel and rephrase.",
        "training": {"track": "Agent Orchestration", "module": "Managing Agent Loops", "priority": "high"},
    },
    {
        "id": "session-drift",
        "name": "Session Drift",
        "group": "session-hygiene",
        "severity": "medium",
        "description": "Sessions accumulate 30+ requests, diluting context and quality.",
        "suggestion": "Keep sessions focused on a single task; start a new session for new topics.",
        "training": {"track": "Agent Orchestration", "module": "Session Management", "priority": "medium"},
    },
    {
        "id": "mega-sessions",
        "name": "Mega Sessions",
        "group": "session-hygiene",
        "severity": "medium",
        "description": "Sessions with 50+ requests indicate context overload and runaway complexity.",
        "suggestion": "Break complex work into smaller, focused sessions.",
        "training": {"track": "Agent Orchestration", "module": "Breaking Down Complex Tasks", "priority": "medium"},
    },
    {
        "id": "high-cancellation",
        "name": "High Cancellation Rate",
        "group": "session-hygiene",
        "severity": "medium",
        "description": "A high proportion of requests are cancelled, wasting tokens and indicating misprompting.",
        "suggestion": "Refine prompts before sending; cancel only when truly necessary.",
        "training": {"track": "Workflow Optimization", "module": "Reducing Cancellations", "priority": "medium"},
    },
    {
        "id": "frustration-signals",
        "name": "Frustration Signals",
        "group": "session-hygiene",
        "severity": "medium",
        "description": "Signs of frustration (retries, expletives, repeated cancellations) detected in sessions.",
        "suggestion": "Step back and re-scope the task when frustration signals appear.",
        "training": {"track": "Workflow Optimization", "module": "Managing AI Frustration", "priority": "medium"},
    },
    # --- Context Management ---
    {
        "id": "context-engineering-gaps",
        "name": "Context Engineering Gaps",
        "group": "context-management",
        "severity": "medium",
        "description": "Missing context engineering setup: no custom agents, skills, MCP tools, file references, or custom instructions.",
        "suggestion": "Set up AGENTS.md, skills, MCP tools, file references, and custom instructions.",
        "training": {"track": "Context Engineering", "module": "Setting Up AGENTS.md & Skills", "priority": "high"},
    },
    {
        "id": "tunnel-vision",
        "name": "Tunnel Vision",
        "group": "context-management",
        "severity": "low",
        "description": "Work is concentrated in a single project/workspace with no diversification.",
        "suggestion": "Diversify project context to broaden the model's useful context.",
        "training": {"track": "Workflow Optimization", "module": "Diversifying Project Context", "priority": "low"},
    },
    # --- Work-Life Balance (session-hygiene group) ---
    {
        "id": "late-night-coding",
        "name": "Late-Night Coding",
        "group": "session-hygiene",
        "severity": "low",
        "description": "A significant portion of AI usage occurs during late-night hours (22:00-05:00).",
        "suggestion": "Encourage sustainable working hours; late-night AI use correlates with lower quality.",
        "training": {"track": "Work-Life Balance", "module": "Sustainable AI Usage", "priority": "low"},
    },
    {
        "id": "weekend-overwork",
        "name": "Weekend Overwork",
        "group": "session-hygiene",
        "severity": "low",
        "description": "Heavy AI usage on weekends indicates potential overwork.",
        "suggestion": "Protect weekend rest; monitor for burnout signals.",
        "training": {"track": "Work-Life Balance", "module": "Sustainable AI Usage", "priority": "low"},
    },
    # --- Plan Efficiency ---
    {
        "id": "rolling-window-pressure",
        "name": "Rolling Window Pressure",
        "group": "plan-efficiency",
        "severity": "medium",
        "description": "Estimated usage is close to or above a per-user rolling-window quota, such as a Claude team/enterprise seat window.",
        "suggestion": "Before upgrading, check whether the pressure comes from valuable high-leverage work, repeated prompts, or poor model routing.",
        "training": {"track": "Model & Tool Selection", "module": "Rolling Window Budget Management", "priority": "high"},
    },
]

# Default governance after AIQ rule audit. Keep rules that measure engineering
# behavior; leave weak, intrusive, or tool-specific proxies available but off.
DEFAULT_RULE_POLICY: dict[str, dict[str, object]] = {
    "lazy-prompting": {"audit_status": "watch", "basis": "Short prompts are noisy, but useful when they dominate a period."},
    "repeated-prompts": {"audit_status": "keep", "basis": "Repeated asks are a direct rework/friction signal."},
    "no-spec-driven-development": {"audit_status": "keep", "basis": "Agentic-coding guidance favors explicit task definitions and acceptance criteria."},
    "verbose-prompt-no-compression": {"audit_status": "keep", "basis": "Context engineering favors selection/compression over dumping large prompts."},
    "no-plan-mode": {"default_enabled": False, "audit_status": "off", "basis": "Tool-specific proxy. Planning matters, but plan-mode telemetry is not portable."},
    "no-skills": {"default_enabled": False, "audit_status": "off", "basis": "Claude-specific proxy. Reuse is good, but not every team uses AIQ skills."},
    "speed-accept": {"audit_status": "keep", "basis": "Human verification is a core AI-code safety practice."},
    "copy-paste-blindness": {"audit_status": "watch", "basis": "Review behavior matters, but file-reference absence is only a proxy."},
    "premium-waste": {"audit_status": "keep", "basis": "Cost routing is valid when the turn is truly low-context and no work is produced."},
    "premium-for-lookup-questions": {"audit_status": "keep", "basis": "Simple lookup routing is a direct plan-efficiency signal."},
    "model-overreliance": {"audit_status": "watch", "basis": "Useful for API spend; lower priority on fixed or rolling seats."},
    "runaway-agent-loops": {"audit_status": "keep", "basis": "Tool-loop volume is a measurable waste/reliability signal."},
    "session-drift": {"audit_status": "keep", "basis": "Long sessions increase context drift risk; use as a coaching signal."},
    "mega-sessions": {"audit_status": "keep", "basis": "Extreme sessions are stronger context/cost risk than normal long work."},
    "high-cancellation": {"audit_status": "keep", "basis": "Cancellations directly show wasted turns or misalignment."},
    "frustration-signals": {"audit_status": "watch", "basis": "Useful friction signal, but never a performance judgment."},
    "context-engineering-gaps": {"audit_status": "keep", "basis": "Context engineering research emphasizes file/context selection, tools, and reusable instructions."},
    "tunnel-vision": {"default_enabled": False, "audit_status": "off", "basis": "Single-project focus is often healthy; this is not a useful anti-pattern."},
    "late-night-coding": {"default_enabled": False, "audit_status": "off", "basis": "Lifestyle surveillance is not an AI-efficiency rule."},
    "weekend-overwork": {"default_enabled": False, "audit_status": "off", "basis": "Lifestyle surveillance is not an AI-efficiency rule."},
    "rolling-window-pressure": {"audit_status": "keep", "basis": "Quota pressure is valid when plan context is explicitly configured."},
}


def _with_policy(rule: dict) -> dict:
    out = dict(rule)
    policy = DEFAULT_RULE_POLICY.get(out["id"], {})
    out.setdefault("default_enabled", bool(policy.get("default_enabled", True)))
    out.setdefault("audit_status", str(policy.get("audit_status", "keep")))
    out.setdefault("basis", str(policy.get("basis", "Observable log signal.")))
    return out

# Quick lookup by rule id.
RULES_BY_ID: dict[str, dict] = {r["id"]: _with_policy(r) for r in RULES_META}

# Ordered set of all rule ids (order is stable and matches RULES_META).
ALL_RULE_IDS: list[str] = [r["id"] for r in RULES_META]


def get_rule(rule_id: str) -> dict | None:
    """Return the metadata dict for a rule id, or None if unknown."""
    return RULES_BY_ID.get(rule_id)


def all_rules() -> list[dict]:
    """Return metadata for all rules (a fresh list of plain dicts)."""
    return [_with_policy(r) for r in RULES_META]
