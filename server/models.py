"""Pydantic models for the AIECO dashboard API.

Models are intentionally flexible: the collector payload contains dynamic
fields (model_usage, activity, work_types) whose shape may evolve, so those
are typed as ``dict`` / ``list[dict]`` rather than strict sub-models. The
fields the server *does* care about (summary metrics, practice scores,
anti-patterns) are modeled explicitly so they can be extracted into the
relational tables for fast querying.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Ingest request (collector -> server)
# ---------------------------------------------------------------------------


class SummaryModel(BaseModel):
    """Summary metrics extracted from the snapshot's ``summary`` object.

    All fields are optional with sensible defaults so the server tolerates
    collectors that omit some metrics.
    """

    total_sessions: int = 0
    total_requests: int = 0
    total_workspaces: int = 0
    total_ai_loc: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    estimated_cost_usd: float = 0.0

    # Allow extra fields (e.g. total_cost, unique_models) to pass through.
    model_config = {"extra": "allow"}


class PracticeScoresModel(BaseModel):
    """The five practice scores (0-100 each)."""

    prompt_quality: float = 0.0
    session_hygiene: float = 0.0
    code_review: float = 0.0
    tool_mastery: float = 0.0
    context_management: float = 0.0

    model_config = {"extra": "allow"}


class AntiPatternModel(BaseModel):
    """A single anti-pattern entry from the snapshot."""

    rule_id: str
    rule_name: str | None = None
    rule_group: str | None = None
    severity: str | None = None
    triggered: bool = False
    occurrences: int = 0
    total: int = 0
    examples: list[str] | None = None

    model_config = {"extra": "allow"}


class IngestRequest(BaseModel):
    """Full payload POSTed by a collector to /api/ingest."""

    employee_id: str
    employee_name: str | None = None
    team: str | None = None
    collected_at: str | None = None
    period_start: str | None = None
    period_end: str | None = None

    summary: SummaryModel = Field(default_factory=SummaryModel)
    practice_scores: PracticeScoresModel = Field(default_factory=PracticeScoresModel)
    anti_patterns: list[AntiPatternModel] = Field(default_factory=list)

    # Dynamic / free-form sections stored as-is in payload_json.
    model_usage: dict[str, Any] = Field(default_factory=dict)
    work_types: dict[str, Any] = Field(default_factory=dict)
    activity: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class IngestResponse(BaseModel):
    status: str = "ok"
    snapshot_id: int


class HealthResponse(BaseModel):
    status: str
    db_path: str
    employee_count: int


class RegisterRequest(BaseModel):
    invite_code: str
    employee_id: str | None = None
    name: str | None = None
    team: str | None = None


class RegisterResponse(BaseModel):
    employee_id: str
    api_key: str
    key_prefix: str
    name: str | None = None
    team: str | None = None


class InviteCreateRequest(BaseModel):
    code: str | None = None
    team: str | None = None
    uses_remaining: int = 1


class InviteCreateResponse(BaseModel):
    code: str
    team: str | None = None
    uses_remaining: int


class MessageResponse(BaseModel):
    """Generic error/info message response."""

    detail: str


# ---------------------------------------------------------------------------
# Helper builders for dict-based responses
# (The richer endpoints return dicts assembled from DB rows, so they don't
# need strict models, but we keep these type aliases for readability.)
# ---------------------------------------------------------------------------

EmployeesList = list[dict[str, Any]]
EmployeeDetail = dict[str, Any]
HistoryList = list[dict[str, Any]]
TeamOverview = dict[str, Any]
RulesList = list[dict[str, Any]]
