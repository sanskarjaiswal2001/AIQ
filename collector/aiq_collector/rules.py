"""
Anti-pattern detection rules.

Each rule is a function ``(sessions) -> DetectionResult`` implementing the
detection logic ported from Microsoft's AI-Engineering-Coach (TypeScript).

Rules operate on a list of :class:`~collector.models.Session` objects and
return :class:`~collector.models.DetectionResult` instances.

Stdlib-only.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Callable

from .models import (
    DetectionResult,
    Session,
    SessionRequest,
    LONG_SESSION_REQS,
    MEGA_SESSION_REQS,
    SPEED_ACCEPT_MS,
    SPEED_ACCEPT_LOC,
    RUNAWAY_TOOL_COUNT,
)

# ---------------------------------------------------------------------------
# Registry — ordered list of (rule_id, function) pairs
# ---------------------------------------------------------------------------

RuleFunc = Callable[[list[Session]], DetectionResult]
RULE_REGISTRY: list[tuple[str, RuleFunc]] = []


def register(rule_id: str) -> Callable[[RuleFunc], RuleFunc]:
    """Decorator that registers a rule function under ``rule_id``."""
    def deco(fn: RuleFunc) -> RuleFunc:
        RULE_REGISTRY.append((rule_id, fn))
        return fn
    return deco


def run_all_rules(sessions: list[Session]) -> list[DetectionResult]:
    """Run every registered rule against ``sessions`` and return results."""
    return [fn(sessions) for _, fn in RULE_REGISTRY]


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_LOOKUP_QUESTION_RE = re.compile(
    r"\b(what(?:'s| is)\b|where(?:'s| is)?\b|how (?:do|does|to)\b|"
    r"why(?:'s| is)?\b|explain\b|which\b|who\b|when\b|"
    r"can you (?:explain|tell|describe)|tell me about)\b",
    re.IGNORECASE,
)

_SPEC_KEYWORDS = re.compile(
    r"\b(requirements|acceptance criteri|spec|\.md\b|\.spec\b|\.plan\b|"
    r"must\s|ensure\s|shall\s|expected behavior|definition of done)\b",
    re.IGNORECASE,
)

_BULLET_RE = re.compile(r"^\s*[-*]\s+", re.MULTILINE)

# Frustration signal phrases
_FRUSTRATION_PATTERNS = re.compile(
    r"(!{2,}|\?{3,}|wtf|wth|why is this|this is wrong|are you kidding|"
    r"what the hell|come on|seriously\?|ugh|dammit|goddammit|this is broken|"
    r"not working again|still broken|you keep|stop doing|why does it keep)",
    re.IGNORECASE,
)

_WEEKDAYS = {5: "Saturday", 6: "Sunday"}  # Mon=0 … Sun=6


def _all_requests(sessions: list[Session]) -> list[tuple[Session, SessionRequest]]:
    """Flatten sessions into (session, request) pairs."""
    out: list[tuple[Session, SessionRequest]] = []
    for s in sessions:
        for r in s.requests:
            out.append((s, r))
    return out


def _file_refs(req: SessionRequest) -> bool:
    """True if the request references any file (prompt mentions a path, or
    edited/referenced file lists are non-empty)."""
    if req.referenced_files or req.edited_files:
        return True
    # crude path mention in prompt: /foo/bar.ext or .py / .ts etc.
    if re.search(r"[\w/\\]+\.\w{1,5}\b", req.message):
        return True
    return False


def _cap_examples(items: list[str], limit: int = 5) -> list[str]:
    """Return up to ``limit`` unique examples, preserving order."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
        if len(out) >= limit:
            break
    return out


# ===========================================================================
# Rules — prompt quality
# ===========================================================================


@register("lazy-prompting")
def rule_lazy_prompting(sessions: list[Session]) -> DetectionResult:
    """Short prompts (< 30 chars, > 0). Triggered when ratio > 0.3 AND count > 10."""
    res = DetectionResult(
        rule_id="lazy-prompting",
        name="Lazy Prompting",
        group="prompt-quality",
        severity="medium",
        description="Very short prompts (< 30 characters) make up a large share of requests.",
        suggestion="Add context, file references, and acceptance criteria to prompts.",
    )
    reqs = _all_requests(sessions)
    total = len(reqs)
    short = [(s, r) for s, r in reqs if 0 < r.message_length < 30]
    res.occurrences = len(short)
    res.total = total
    if total == 0:
        return res
    ratio = len(short) / total
    res.triggered = ratio > 0.3 and len(short) > 10
    res.examples = _cap_examples([r.message[:60] for _, r in short])
    return res


@register("repeated-prompts")
def rule_repeated_prompts(sessions: list[Session]) -> DetectionResult:
    """Near-duplicate prompts (first 60 chars match). 3+ duplicates needed."""
    res = DetectionResult(
        rule_id="repeated-prompts",
        name="Repeated Prompts",
        group="prompt-quality",
        severity="medium",
        description="Near-duplicate prompts appear repeatedly, suggesting iterative re-asking.",
        suggestion="Refine the prompt once and iterate within a single thread.",
    )
    reqs = _all_requests(sessions)
    total = len(reqs)
    prefix_counts: Counter[str] = Counter()
    prefix_to_full: dict[str, str] = {}
    for _, r in reqs:
        if r.message_length == 0:
            continue
        key = r.message[:60].strip().lower()
        if not key:
            continue
        prefix_counts[key] += 1
        prefix_to_full.setdefault(key, r.message[:80])
    dupes = {k: c for k, c in prefix_counts.items() if c >= 3}
    res.occurrences = sum(c for c in dupes.values())
    res.total = total
    res.triggered = len(dupes) > 0 and res.occurrences >= 3
    res.examples = _cap_examples([prefix_to_full[k] for k in dupes])
    return res


@register("no-spec-driven-development")
def rule_no_spec_driven(sessions: list[Session]) -> DetectionResult:
    """Few sessions start with specs. Spec rate < 0.2 AND 5+ agent sessions."""
    res = DetectionResult(
        rule_id="no-spec-driven-development",
        name="No Spec-Driven Development",
        group="prompt-quality",
        severity="medium",
        description="Sessions rarely begin with specifications, plans, or acceptance criteria.",
        suggestion="Start sessions by referencing .md/.spec/.plan files or listing requirements.",
    )
    agent_sessions = [s for s in sessions if any(r.is_agent_mode or r.has_subagents for r in s.requests)]
    total = len(agent_sessions)
    if total == 0:
        res.total = 0
        return res
    spec_sessions = 0
    for s in agent_sessions:
        if not s.requests:
            continue
        first = s.requests[0]
        msg = first.message.lower()
        has_spec = bool(_SPEC_KEYWORDS.search(first.message))
        if not has_spec:
            has_spec = bool(_BULLET_RE.search(first.message))
        if not has_spec:
            has_spec = first.is_plan_mode
        if has_spec:
            spec_sessions += 1
    spec_rate = spec_sessions / total
    res.occurrences = total - spec_sessions
    res.total = total
    res.triggered = spec_rate < 0.2 and total >= 5
    return res


@register("context-engineering-gaps")
def rule_context_engineering_gaps(sessions: list[Session]) -> DetectionResult:
    """Audit 5 signals: subAgents, skills, mcp, fileRefRate < 0.1, instrRate < 0.05.
    Count missing signals. Only evaluated when total requests >= 30."""
    res = DetectionResult(
        rule_id="context-engineering-gaps",
        name="Context Engineering Gaps",
        group="prompt-quality",
        severity="medium",
        description="Missing context-engineering signals (sub-agents, skills, MCP, file refs, instructions).",
        suggestion="Use skills, MCP tools, file references, and explicit instructions to provide context.",
    )
    reqs = _all_requests(sessions)
    total = len(reqs)
    res.total = total
    if total < 30:
        return res
    has_subagents = any(r.has_subagents for _, r in reqs)
    has_skills = any(r.has_skills for _, r in reqs)
    has_mcp = any(r.has_mcp for _, r in reqs)
    file_ref_count = sum(1 for _, r in reqs if _file_refs(r))
    file_ref_rate = file_ref_count / total if total else 0
    # instrRate: prompts containing imperative instruction keywords
    instr_count = sum(
        1 for _, r in reqs
        if re.search(r"\b(must|should|ensure|need to|require|please|make sure)\b", r.message, re.IGNORECASE)
    )
    instr_rate = instr_count / total if total else 0
    gaps = 0
    if not has_subagents:
        gaps += 1
    if not has_skills:
        gaps += 1
    if not has_mcp:
        gaps += 1
    if file_ref_rate < 0.1:
        gaps += 1
    if instr_rate < 0.05:
        gaps += 1
    res.occurrences = gaps
    res.triggered = gaps >= 3
    return res


@register("verbose-prompt-no-compression")
def rule_verbose_no_compression(sessions: list[Session]) -> DetectionResult:
    """Prompts > 500 chars without file references. Ratio > 0.3 triggers."""
    res = DetectionResult(
        rule_id="verbose-prompt-no-compression",
        name="Verbose Prompt Without Compression",
        group="prompt-quality",
        severity="medium",
        description="Long prompts (> 500 chars) without file references, suggesting uncompressed context.",
        suggestion="Move verbose context into referenced files or compact summaries.",
    )
    reqs = _all_requests(sessions)
    total = len(reqs)
    verbose = [(s, r) for s, r in reqs if r.message_length > 500 and not _file_refs(r)]
    res.occurrences = len(verbose)
    res.total = total
    if total == 0:
        return res
    ratio = len(verbose) / total
    res.triggered = ratio > 0.3
    res.examples = _cap_examples([r.message[:80] + "…" for _, r in verbose])
    return res


@register("no-plan-mode")
def rule_no_plan_mode(sessions: list[Session]) -> DetectionResult:
    """< 15% of sessions use plan mode."""
    res = DetectionResult(
        rule_id="no-plan-mode",
        name="No Plan Mode",
        group="prompt-quality",
        severity="low",
        description="Plan mode is rarely or never used before implementation.",
        suggestion="Use plan mode for complex tasks to review the approach before code changes.",
    )
    total = len(sessions)
    res.total = total
    if total == 0:
        return res
    plan_sessions = sum(1 for s in sessions if s.has_plan_mode)
    res.occurrences = total - plan_sessions
    plan_rate = plan_sessions / total
    res.triggered = plan_rate < 0.15
    return res


@register("no-skills")
def rule_no_skills(sessions: list[Session]) -> DetectionResult:
    """Zero skills used across all sessions with 30+ requests."""
    res = DetectionResult(
        rule_id="no-skills",
        name="No Skills Used",
        group="prompt-quality",
        severity="low",
        description="No Claude Code skills are used despite substantial activity (30+ requests).",
        suggestion="Create and use skills for repeated workflows to improve consistency.",
    )
    reqs = _all_requests(sessions)
    total = len(reqs)
    res.total = total
    if total < 30:
        return res
    any_skills = any(r.has_skills for _, r in reqs) or any(s.has_skills for s in sessions)
    res.occurrences = 0 if any_skills else 1
    res.triggered = not any_skills
    return res


@register("tunnel-vision")
def rule_tunnel_vision(sessions: list[Session]) -> DetectionResult:
    """>90% of sessions in a single workspace."""
    res = DetectionResult(
        rule_id="tunnel-vision",
        name="Tunnel Vision",
        group="prompt-quality",
        severity="medium",
        description="Over 90% of sessions are concentrated in a single workspace.",
        suggestion="Distribute work across workspaces or consolidate related projects.",
    )
    total = len(sessions)
    res.total = total
    if total == 0:
        return res
    ws_counts: Counter[str] = Counter(s.workspace_name for s in sessions)
    top_ws, top_count = ws_counts.most_common(1)[0]
    ratio = top_count / total
    res.occurrences = top_count
    res.triggered = ratio > 0.9
    res.examples = [top_ws] if res.triggered else []
    return res


# ===========================================================================
# Rules — code review
# ===========================================================================


@register("speed-accept")
def rule_speed_accept(sessions: list[Session]) -> DetectionResult:
    """Adjacent request pairs where AI produced 20+ LOC and next message came
    within 15 seconds. 5+ occurrences → no code review."""
    res = DetectionResult(
        rule_id="speed-accept",
        name="Speed Accept (No Code Review)",
        group="code-review",
        severity="high",
        description="Code was accepted within 15 seconds of AI producing 20+ lines, indicating no review.",
        suggestion="Review AI-generated code before sending the next prompt.",
    )
    occurrences = 0
    examples: list[str] = []
    total = 0
    for s in sessions:
        reqs = s.requests
        for i in range(len(reqs) - 1):
            total += 1
            cur = reqs[i]
            nxt = reqs[i + 1]
            if cur.ai_loc >= SPEED_ACCEPT_LOC and 0 < cur.elapsed_ms < SPEED_ACCEPT_MS:
                occurrences += 1
                if len(examples) < 5:
                    examples.append(nxt.message[:80])
    res.occurrences = occurrences
    res.total = total
    res.triggered = occurrences >= 5
    res.examples = _cap_examples(examples)
    return res


@register("copy-paste-blindness")
def rule_copy_paste_blindness(sessions: list[Session]) -> DetectionResult:
    """Sessions where AI code LOC > 50 and user never references files or uses
    tools themselves."""
    res = DetectionResult(
        rule_id="copy-paste-blindness",
        name="Copy-Paste Blindness",
        group="code-review",
        severity="medium",
        description="AI produces substantial code but the user never references files or uses tools, suggesting blind acceptance.",
        suggestion="Read the affected files and review diffs before accepting AI output.",
    )
    total = len(sessions)
    occurrences = 0
    examples: list[str] = []
    for s in sessions:
        if s.total_ai_loc <= 50:
            continue
        # user never references files and never uses tools themselves
        user_refs_files = any(_file_refs(r) for r in s.requests)
        # "user uses tools themselves" — not applicable in Claude Code (tools are
        # AI-invoked), so we treat "references files" as the primary signal.
        if not user_refs_files:
            occurrences += 1
            if len(examples) < 5:
                examples.append(s.workspace_name)
    res.occurrences = occurrences
    res.total = total
    res.triggered = occurrences >= 1
    res.examples = _cap_examples(examples)
    return res


# ===========================================================================
# Rules — tool mastery
# ===========================================================================


@register("premium-waste")
def rule_premium_waste(sessions: list[Session]) -> DetectionResult:
    """Simple requests (messageLength < 50, no AI code output) using premium
    models. 10+ occurrences. Premium = modelTier >= 1."""
    from .scoring import model_tier

    res = DetectionResult(
        rule_id="premium-waste",
        name="Premium Model Waste",
        group="tool-mastery",
        severity="medium",
        description="Premium models are used for simple requests that produce no code.",
        suggestion="Route trivial requests to a cheaper/free model tier.",
    )
    occurrences = 0
    examples: list[str] = []
    total = 0
    for _, r in _all_requests(sessions):
        total += 1
        model = r.model
        if not model or model == "<synthetic>":
            continue
        if model_tier(model) >= 1 and r.message_length < 50 and r.ai_loc == 0:
            occurrences += 1
            if len(examples) < 5:
                examples.append(f"[{model}] {r.message[:60]}")
    res.occurrences = occurrences
    res.total = total
    res.triggered = occurrences >= 10
    res.examples = _cap_examples(examples)
    return res


@register("premium-for-lookup-questions")
def rule_premium_for_lookups(sessions: list[Session]) -> DetectionResult:
    """Lookup-style questions using premium models, messageLength < 120, no
    code, no tools. Ratio > 0.1 AND count > 10."""
    from .scoring import model_tier

    res = DetectionResult(
        rule_id="premium-for-lookup-questions",
        name="Premium Model For Lookup Questions",
        group="tool-mastery",
        severity="medium",
        description="Premium models answer simple lookup questions that need no code or tools.",
        suggestion="Use a cheaper model for factual/lookup questions.",
    )
    occurrences = 0
    total = 0
    examples: list[str] = []
    for _, r in _all_requests(sessions):
        if r.message_length == 0:
            continue
        total += 1
        model = r.model
        if not model or model == "<synthetic>":
            continue
        is_lookup = bool(_LOOKUP_QUESTION_RE.search(r.message))
        if (model_tier(model) >= 1 and is_lookup
                and r.message_length < 120 and r.ai_loc == 0
                and r.tool_count == 0):
            occurrences += 1
            if len(examples) < 5:
                examples.append(f"[{model}] {r.message[:60]}")
    res.occurrences = occurrences
    res.total = total
    if total == 0:
        return res
    ratio = occurrences / total
    res.triggered = ratio > 0.1 and occurrences > 10
    res.examples = _cap_examples(examples)
    return res


@register("model-overreliance")
def rule_model_overreliance(sessions: list[Session]) -> DetectionResult:
    """>80% of requests use a single model AND < 3 models used AND > 10 total
    requests."""
    res = DetectionResult(
        rule_id="model-overreliance",
        name="Model Overreliance",
        group="tool-mastery",
        severity="medium",
        description="A single model handles over 80% of requests with little model diversity.",
        suggestion="Match model tier to task complexity to reduce cost and overreliance.",
    )
    model_counts: Counter[str] = Counter()
    total = 0
    for _, r in _all_requests(sessions):
        if not r.model or r.model == "<synthetic>":
            continue
        model_counts[r.model] += 1
        total += 1
    res.total = total
    if total == 0:
        return res
    distinct_models = len(model_counts)
    top_model, top_count = model_counts.most_common(1)[0]
    ratio = top_count / total
    res.occurrences = top_count
    res.triggered = ratio > 0.8 and distinct_models < 3 and total > 10
    res.examples = [top_model] if res.triggered else []
    return res


# ===========================================================================
# Rules — session hygiene
# ===========================================================================


@register("runaway-agent-loops")
def rule_runaway_agent_loops(sessions: list[Session]) -> DetectionResult:
    """Agentic requests using 15+ tools each. 3+ such requests. Agent mode or
    agentName present."""
    res = DetectionResult(
        rule_id="runaway-agent-loops",
        name="Runaway Agent Loops",
        group="session-hygiene",
        severity="high",
        description="Agent requests invoke 15+ tools each, suggesting uncontrolled loops.",
        suggestion="Set tool-use limits and break long agent runs into smaller tasks.",
    )
    occurrences = 0
    total = 0
    examples: list[str] = []
    for s in sessions:
        for r in s.requests:
            total += 1
            is_agent = r.is_agent_mode or r.has_subagents or bool(r.agent_name)
            if is_agent and r.tool_count >= RUNAWAY_TOOL_COUNT:
                occurrences += 1
                if len(examples) < 5:
                    examples.append(f"{s.workspace_name}: {r.tool_count} tools")
    res.occurrences = occurrences
    res.total = total
    res.triggered = occurrences >= 3
    res.examples = _cap_examples(examples)
    return res


@register("session-drift")
def rule_session_drift(sessions: list[Session]) -> DetectionResult:
    """Sessions with 30+ requests (LONG_SESSION_REQS)."""
    res = DetectionResult(
        rule_id="session-drift",
        name="Session Drift",
        group="session-hygiene",
        severity="medium",
        description="Sessions exceed 30 requests, indicating scope creep or context drift.",
        suggestion="Start fresh sessions when context drifts; archive long ones.",
    )
    total = len(sessions)
    long_sessions = [s for s in sessions if s.request_count >= LONG_SESSION_REQS]
    res.occurrences = len(long_sessions)
    res.total = total
    res.triggered = len(long_sessions) >= 1
    res.examples = _cap_examples([f"{s.workspace_name} ({s.request_count} reqs)" for s in long_sessions])
    return res


@register("late-night-coding")
def rule_late_night_coding(sessions: list[Session]) -> DetectionResult:
    """Requests between 22:00–05:00 local time."""
    res = DetectionResult(
        rule_id="late-night-coding",
        name="Late-Night Coding",
        group="session-hygiene",
        severity="low",
        description="Requests are made between 22:00 and 05:00, a potential burnout signal.",
        suggestion="Avoid late-night AI sessions; rest improves code review quality.",
    )
    occurrences = 0
    total = 0
    examples: list[str] = []
    for _, r in _all_requests(sessions):
        if not r.timestamp_dt:
            continue
        total += 1
        hour = r.timestamp_dt.hour
        if hour >= 22 or hour < 5:
            occurrences += 1
            if len(examples) < 5:
                examples.append(r.timestamp[:19])
    res.occurrences = occurrences
    res.total = total
    res.triggered = occurrences >= 3
    res.examples = _cap_examples(examples)
    return res


@register("weekend-overwork")
def rule_weekend_overwork(sessions: list[Session]) -> DetectionResult:
    """Requests on Saturday/Sunday."""
    res = DetectionResult(
        rule_id="weekend-overwork",
        name="Weekend Overwork",
        group="session-hygiene",
        severity="low",
        description="Requests are made on weekends, a potential overwork signal.",
        suggestion="Keep weekend AI usage intentional and bounded.",
    )
    occurrences = 0
    total = 0
    examples: list[str] = []
    for _, r in _all_requests(sessions):
        if not r.timestamp_dt:
            continue
        total += 1
        if r.timestamp_dt.weekday() in _WEEKDAYS:
            occurrences += 1
            if len(examples) < 5:
                examples.append(f"{r.timestamp_dt.strftime('%A')} {r.timestamp[:10]}")
    res.occurrences = occurrences
    res.total = total
    res.triggered = occurrences >= 3
    res.examples = _cap_examples(examples)
    return res


@register("high-cancellation")
def rule_high_cancellation(sessions: list[Session]) -> DetectionResult:
    """>20% of requests canceled."""
    res = DetectionResult(
        rule_id="high-cancellation",
        name="High Cancellation Rate",
        group="session-hygiene",
        severity="medium",
        description="Over 20% of requests are canceled, suggesting misaligned prompts or slow responses.",
        suggestion="Refine prompts upfront and reduce mid-response cancellations.",
    )
    reqs = _all_requests(sessions)
    total = len(reqs)
    canceled = sum(1 for _, r in reqs if r.is_canceled)
    res.occurrences = canceled
    res.total = total
    if total == 0:
        return res
    res.triggered = (canceled / total) > 0.20
    return res


@register("frustration-signals")
def rule_frustration_signals(sessions: list[Session]) -> DetectionResult:
    """Prompts containing frustration markers: !!!, ???, wtf, etc."""
    res = DetectionResult(
        rule_id="frustration-signals",
        name="Frustration Signals",
        group="session-hygiene",
        severity="medium",
        description="Prompts contain frustration markers (!!!, ???, wtf, …), indicating friction.",
        suggestion="Step back and restructure the task when frustration appears.",
    )
    occurrences = 0
    total = 0
    examples: list[str] = []
    for _, r in _all_requests(sessions):
        if r.message_length == 0:
            continue
        total += 1
        if _FRUSTRATION_PATTERNS.search(r.message):
            occurrences += 1
            if len(examples) < 5:
                examples.append(r.message[:80])
    res.occurrences = occurrences
    res.total = total
    res.triggered = occurrences >= 3
    res.examples = _cap_examples(examples)
    return res


@register("mega-sessions")
def rule_mega_sessions(sessions: list[Session]) -> DetectionResult:
    """Sessions with 50+ requests."""
    res = DetectionResult(
        rule_id="mega-sessions",
        name="Mega Sessions",
        group="session-hygiene",
        severity="medium",
        description="Sessions exceed 50 requests, a strong context-drift and cost signal.",
        suggestion="Split mega sessions into focused sub-sessions.",
    )
    total = len(sessions)
    mega = [s for s in sessions if s.request_count >= MEGA_SESSION_REQS]
    res.occurrences = len(mega)
    res.total = total
    res.triggered = len(mega) >= 1
    res.examples = _cap_examples([f"{s.workspace_name} ({s.request_count} reqs)" for s in mega])
    return res
