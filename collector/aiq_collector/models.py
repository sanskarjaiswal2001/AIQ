"""
Data models for the AI-Engineering-Coach edge collector.

Defines dataclasses for parsed Claude Code sessions, requests, tool uses,
code blocks, and anti-pattern detection results. Pure data — no parsing
or analysis logic lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ---------------------------------------------------------------------------
# Constants — tool name → action classification
# ---------------------------------------------------------------------------

# Tools that write/edit files (extract ``file_path`` from input → editedFiles)
WRITE_TOOLS: frozenset[str] = frozenset({"Write", "Edit", "MultiEditTool", "MultiEdit"})

# Tools that read a single file by path (extract ``file_path`` → referencedFiles)
READ_FILE_TOOLS: frozenset[str] = frozenset({"Read", "View"})

# Tools that list/glob paths (extract ``path`` / ``pattern`` → referencedFiles)
READ_PATH_TOOLS: frozenset[str] = frozenset({"Glob", "LS", "Find", "Search"})

# Thresholds reused across rules / scoring
LONG_SESSION_REQS = 30      # session-drift threshold
MEGA_SESSION_REQS = 50      # mega-sessions threshold
SPEED_ACCEPT_MS = 15_000    # speed-accept: next msg within 15 s
SPEED_ACCEPT_LOC = 20       # speed-accept: 20+ LOC produced
RUNAWAY_TOOL_COUNT = 15     # runaway-agent-loops: 15+ tools in a request


# ---------------------------------------------------------------------------
# Code block + tool use
# ---------------------------------------------------------------------------


@dataclass
class CodeBlock:
    """A code block extracted from response text or a Write/Edit tool input."""

    language: str = ""
    loc: int = 0
    source: str = "text"          # "text" | "write" | "edit"
    file_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "language": self.language,
            "loc": self.loc,
            "source": self.source,
            "file_path": self.file_path,
        }


@dataclass
class ToolUseRecord:
    """A single tool invocation parsed from an assistant content block."""

    name: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    file_path: str = ""

    @property
    def is_write_tool(self) -> bool:
        return self.name in WRITE_TOOLS

    @property
    def is_read_file_tool(self) -> bool:
        return self.name in READ_FILE_TOOLS

    @property
    def is_read_path_tool(self) -> bool:
        return self.name in READ_PATH_TOOLS

    @property
    def is_skill_tool(self) -> bool:
        return self.name == "Skill"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "file_path": self.file_path,
        }


# ---------------------------------------------------------------------------
# Session + request
# ---------------------------------------------------------------------------


@dataclass
class SessionRequest:
    """One user prompt + all assistant turns that follow until the next real
    user prompt. This is the core unit of analysis."""

    # --- prompt metadata ---
    message: str = ""
    message_length: int = 0
    timestamp: str = ""
    timestamp_dt: datetime | None = None
    is_canceled: bool = False

    # --- response accumulation across assistant lines ---
    response_text: str = ""
    model: str = ""
    models: list[str] = field(default_factory=list)
    tools_used: list[ToolUseRecord] = field(default_factory=list)
    edited_files: list[str] = field(default_factory=list)
    referenced_files: list[str] = field(default_factory=list)
    skills_used: list[str] = field(default_factory=list)
    code_blocks: list[CodeBlock] = field(default_factory=list)

    # --- token accumulation ---
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    # --- derived flags (filled by analyzer/rules) ---
    is_agent_mode: bool = False
    agent_name: str = ""
    is_plan_mode: bool = False
    has_subagents: bool = False
    has_mcp: bool = False
    has_skills: bool = False
    elapsed_ms: int = 0          # duration to *next* real prompt (filled later)

    # --- helpers ---
    @property
    def ai_loc(self) -> int:
        """Total lines of AI-generated code across all code blocks."""
        return sum(cb.loc for cb in self.code_blocks)

    @property
    def tool_count(self) -> int:
        return len(self.tools_used)

    @property
    def user_loc(self) -> int:
        """Approximate lines of code in the user's prompt — non-blank lines."""
        if not self.message:
            return 0
        return sum(1 for line in self.message.splitlines() if line.strip())

    def to_dict(self) -> dict[str, Any]:
        return {
            "message": self.message,
            "message_length": self.message_length,
            "timestamp": self.timestamp,
            "is_canceled": self.is_canceled,
            "model": self.model,
            "tools_used": [t.to_dict() for t in self.tools_used],
            "edited_files": self.edited_files,
            "referenced_files": self.referenced_files,
            "skills_used": self.skills_used,
            "ai_loc": self.ai_loc,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "is_plan_mode": self.is_plan_mode,
            "is_agent_mode": self.is_agent_mode,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class Session:
    """A parsed Claude Code session (one .jsonl file)."""

    session_id: str = ""
    workspace_name: str = ""
    workspace_id: str = ""
    workspace_path: str = ""           # decoded cwd / encoded-path
    git_remote_url: str = ""           # canonical repo identity, if detectable
    harness: str = "claude"            # claude | codex | opencode | cursor | copilot
    creation_date: str = ""
    last_message_date: str = ""
    version: str = ""
    git_branch: str = ""
    requests: list[SessionRequest] = field(default_factory=list)

    # session-level flags
    has_plan_mode: bool = False
    has_subagents: bool = False
    has_skills: bool = False
    has_mcp: bool = False

    # model / token aggregates (filled by analyzer)
    models: set[str] = field(default_factory=set)

    @property
    def request_count(self) -> int:
        return len(self.requests)

    @property
    def total_ai_loc(self) -> int:
        return sum(r.ai_loc for r in self.requests)

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self.requests)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self.requests)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "workspace_name": self.workspace_name,
            "workspace_id": self.workspace_id,
            "workspace_path": self.workspace_path,
            "git_remote_url": self.git_remote_url,
            "harness": self.harness,
            "creation_date": self.creation_date,
            "last_message_date": self.last_message_date,
            "version": self.version,
            "git_branch": self.git_branch,
            "request_count": self.request_count,
            "total_ai_loc": self.total_ai_loc,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "has_plan_mode": self.has_plan_mode,
            "has_skills": self.has_skills,
            "has_mcp": self.has_mcp,
        }


# ---------------------------------------------------------------------------
# Detection result
# ---------------------------------------------------------------------------


@dataclass
class DetectionResult:
    """Result of a single anti-pattern rule evaluation."""

    rule_id: str = ""
    name: str = ""
    group: str = ""
    severity: str = "medium"          # low | medium | high
    description: str = ""
    suggestion: str = ""
    triggered: bool = False
    occurrences: int = 0
    total: int = 0
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "group": self.group,
            "severity": self.severity,
            "description": self.description,
            "suggestion": self.suggestion,
            "triggered": self.triggered,
            "occurrences": self.occurrences,
            "total": self.total,
            "examples": self.examples[:5],     # cap examples in output
        }
