"""Pluggable AI-agent harness parsers for AIQ.

The collector normalizes every supported coding assistant into the existing
``Session`` / ``SessionRequest`` data model. Claude Code keeps its dedicated
parser; Codex/OpenCode/Cursor/Copilot use a tolerant JSON/JSONL parser that
understands common chat-log shapes without adding dependencies.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .models import Session, SessionRequest, ToolUseRecord
from .parser import (
    ClaudeLogParser,
    _parse_iso,
    extract_code_blocks_from_text,
    extract_code_from_tool,
    workspace_name_from_path,
)

SUPPORTED_HARNESSES: tuple[str, ...] = ("claude", "codex", "opencode", "cursor", "copilot")
DEFAULT_HARNESS_DIRS: dict[str, str] = {
    "claude": "~/.claude/projects",
    "codex": "~/.codex",
    "opencode": "~/.opencode",
    "cursor": "~/.cursor",
    "copilot": "~/.config/Code/User/workspaceStorage",
}


@dataclass(frozen=True)
class HarnessSpec:
    name: str
    default_dir: str
    workspace_prefix: str
    globs: tuple[str, ...] = ("**/*.jsonl", "**/*.json")


def parse_harness_list(value: str | Iterable[str] | None) -> list[str]:
    """Parse ``auto`` / comma-separated / iterable harness selection."""
    if value is None or value == "":
        return ["auto"]
    if isinstance(value, str):
        items = [p.strip().lower() for p in value.split(",") if p.strip()]
    else:
        items = [str(p).strip().lower() for p in value if str(p).strip()]
    return items or ["auto"]


def harness_dir(harness: str, overrides: dict[str, str] | None = None) -> Path:
    overrides = overrides or {}
    raw = overrides.get(harness) or DEFAULT_HARNESS_DIRS[harness]
    return Path(os.path.expanduser(raw))


def discover_available_harnesses(overrides: dict[str, str] | None = None) -> dict[str, dict[str, Any]]:
    """Return lightweight availability info for status/config output."""
    out: dict[str, dict[str, Any]] = {}
    for name in SUPPORTED_HARNESSES:
        path = harness_dir(name, overrides)
        out[name] = {
            "path": str(path),
            "exists": path.exists(),
            "default": DEFAULT_HARNESS_DIRS[name],
        }
    return out


def collect_sessions(
    harnesses: str | Iterable[str] | None = "auto",
    *,
    dirs: dict[str, str] | None = None,
) -> list[Session]:
    """Parse all selected harness logs and return normalized sessions.

    ``harnesses='auto'`` parses every supported harness whose configured/default
    directory exists. Explicit selections parse only those harnesses and silently
    return no sessions for missing directories.
    """
    dirs = dirs or {}
    selected = parse_harness_list(harnesses)
    if "auto" in selected:
        selected = [h for h in SUPPORTED_HARNESSES if harness_dir(h, dirs).exists()]
    sessions: list[Session] = []
    for harness in selected:
        if harness not in SUPPORTED_HARNESSES:
            continue
        base = harness_dir(harness, dirs)
        if not base.exists():
            continue
        if harness == "claude":
            sessions.extend(ClaudeLogParser(claude_dir=base).parse_directory())
        else:
            spec = HarnessSpec(harness, DEFAULT_HARNESS_DIRS[harness], harness)
            sessions.extend(GenericJsonAgentParser(spec, base).parse_directory())
    return sessions


class GenericJsonAgentParser:
    """Tolerant parser for JSON/JSONL chat logs from Codex/OpenCode/Cursor/Copilot.

    This is intentionally heuristic: vendors change local log formats often.
    The parser looks for common records with role/type/content/usage/tool fields
    and produces best-effort metrics while ignoring malformed/private content.
    """

    def __init__(self, spec: HarnessSpec, base_dir: str | Path | None = None) -> None:
        self.spec = spec
        self.base_dir = Path(base_dir or os.path.expanduser(spec.default_dir))
        self._claude_classifier = ClaudeLogParser()

    def parse_directory(self, base_dir: str | Path | None = None) -> list[Session]:
        base = Path(base_dir) if base_dir else self.base_dir
        if not base.is_dir():
            return []
        seen: set[Path] = set()
        sessions: list[Session] = []
        for pattern in self.spec.globs:
            for path in sorted(base.glob(pattern)):
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                session = self.parse_file(path)
                if session and session.requests:
                    sessions.append(session)
        return sessions

    def parse_file(self, path: str | Path) -> Session | None:
        path = Path(path)
        records = list(_read_json_records(path))
        if not records:
            return None
        return self._build_session(records, path)

    def _build_session(self, records: list[dict[str, Any]], path: Path) -> Session | None:
        workspace_path = _first_string(records, [
            "cwd", "workspace", "workspace_path", "workspacePath", "project_path", "projectPath", "root", "repo", "repository",
        ]) or _workspace_from_path(path, self.base_dir)
        session = Session(
            session_id=_first_string(records, ["session_id", "sessionId", "conversation_id", "conversationId", "thread_id", "id"]) or path.stem,
            workspace_path=workspace_path,
            workspace_name=workspace_name_from_path(workspace_path),
            workspace_id=f"{self.spec.workspace_prefix}-{_safe_id(workspace_path or path.stem)}",
        )
        session.git_branch = _first_string(records, ["git_branch", "gitBranch", "branch"]) or ""
        session.version = _first_string(records, ["version", "app_version", "agent_version"]) or ""
        requests = self._build_requests(records)
        if not requests:
            return None
        session.requests = requests
        timestamps = [r.timestamp for r in requests if r.timestamp]
        if timestamps:
            session.creation_date = timestamps[0]
            session.last_message_date = timestamps[-1]
        for r in requests:
            for m in r.models:
                if m and m != "<synthetic>":
                    session.models.add(m)
        session.has_plan_mode = any(r.is_plan_mode for r in requests)
        session.has_subagents = any(r.has_subagents for r in requests)
        session.has_skills = any(r.has_skills for r in requests)
        session.has_mcp = any(r.has_mcp for r in requests)
        return session

    def _build_requests(self, records: list[dict[str, Any]]) -> list[SessionRequest]:
        requests: list[SessionRequest] = []
        current: SessionRequest | None = None
        for rec in records:
            role = _record_role(rec)
            if role == "user":
                text = _record_text(rec)
                if not text:
                    continue
                current = SessionRequest(
                    message=text,
                    message_length=len(text),
                    timestamp=_record_timestamp(rec),
                )
                current.timestamp_dt = _parse_iso(current.timestamp)
                current.is_plan_mode = _truthy_any(rec, ["plan_mode", "is_plan_mode", "planning"])
                requests.append(current)
                continue
            if current is None:
                continue
            if role == "assistant":
                self._accumulate_assistant_record(rec, current)
            elif role == "tool":
                self._accumulate_tool_record(rec, current)
            elif _looks_like_usage_record(rec):
                self._accumulate_usage(rec, current)
        for i, req in enumerate(requests[:-1]):
            nxt = requests[i + 1]
            if req.timestamp_dt and nxt.timestamp_dt:
                req.elapsed_ms = int((nxt.timestamp_dt - req.timestamp_dt).total_seconds() * 1000)
        return requests

    def _accumulate_assistant_record(self, rec: dict[str, Any], req: SessionRequest) -> None:
        model = _first_string([rec], ["model", "model_id", "modelId", "engine", "provider_model"]) or ""
        if model:
            req.model = req.model or model
            if model not in req.models:
                req.models.append(model)
        self._accumulate_usage(rec, req)
        text = _record_text(rec)
        if text:
            req.response_text += ("\n" + text) if req.response_text else text
            req.code_blocks.extend(extract_code_blocks_from_text(text))
        for tool in _extract_tool_records(rec):
            self._accumulate_tool_record(tool, req)

    def _accumulate_usage(self, rec: dict[str, Any], req: SessionRequest) -> None:
        usage = _first_dict(rec, ["usage", "token_usage", "tokens", "metrics"]) or rec
        input_tokens = _first_int(usage, ["input_tokens", "prompt_tokens", "input", "prompt", "totalInputTokens"])
        output_tokens = _first_int(usage, ["output_tokens", "completion_tokens", "output", "completion", "totalOutputTokens"])
        cache_read = _first_int(usage, ["cache_read_input_tokens", "cached_input_tokens", "cache_read"])
        cache_write = _first_int(usage, ["cache_creation_input_tokens", "cache_write_input_tokens", "cache_write"])
        req.input_tokens += input_tokens + cache_read + cache_write
        req.output_tokens += output_tokens
        req.cache_read_tokens += cache_read
        req.cache_write_tokens += cache_write

    def _accumulate_tool_record(self, rec: dict[str, Any], req: SessionRequest) -> None:
        name = _canonical_tool_name(_first_string([rec], ["name", "tool", "tool_name", "function", "type"]) or "Tool")
        inp = _first_dict(rec, ["input", "arguments", "args", "params", "parameters"]) or {}
        if not inp:
            inp = {k: v for k, v in rec.items() if k not in {"type", "role", "name", "tool", "tool_name", "function"}}
        tool = ToolUseRecord(name=name, input=inp)
        self._claude_classifier._classify_tool(tool, req)  # reuse existing file/tool classification
        req.tools_used.append(tool)
        for cb in extract_code_from_tool(name, inp):
            req.code_blocks.append(cb)
        if "mcp" in name.lower():
            req.has_mcp = True
        if name in {"Task", "SubAgent"} or "agent" in name.lower():
            req.has_subagents = True


def _read_json_records(path: Path) -> Iterable[dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    if path.suffix.lower() == ".jsonl":
        out: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            out.extend(_flatten_json_records(obj))
        return out
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return []
    return list(_flatten_json_records(obj))


def _flatten_json_records(obj: Any) -> Iterable[dict[str, Any]]:
    if isinstance(obj, list):
        for item in obj:
            yield from _flatten_json_records(item)
    elif isinstance(obj, dict):
        yielded_child = False
        for key in ("messages", "items", "events", "turns", "records", "entries"):
            val = obj.get(key)
            if isinstance(val, list):
                yielded_child = True
                yield from _flatten_json_records(val)
        if not yielded_child:
            yield obj


def _record_role(rec: dict[str, Any]) -> str:
    role = str(rec.get("role") or rec.get("author") or rec.get("sender") or "").lower()
    typ = str(rec.get("type") or rec.get("event") or rec.get("kind") or "").lower()
    if role in {"user", "human"} or typ in {"user", "user_message", "input", "prompt"}:
        return "user"
    if role in {"assistant", "agent", "ai"} or typ in {"assistant", "assistant_message", "message", "response", "completion"}:
        return "assistant"
    if role == "tool" or "tool" in typ or "function_call" in typ:
        return "tool"
    return ""


def _record_text(rec: dict[str, Any]) -> str:
    for key in ("content", "text", "message", "prompt", "response", "output"):
        if key in rec:
            text = _content_to_text(rec.get(key))
            if text:
                return text
    msg = rec.get("message")
    if isinstance(msg, dict):
        return _record_text(msg)
    return ""


def _content_to_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("text", "content", "message", "value", "input_text", "output_text"):
            text = _content_to_text(value.get(key))
            if text:
                return text
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            text = _content_to_text(item)
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _record_timestamp(rec: dict[str, Any]) -> str:
    return _first_string([rec], ["timestamp", "created_at", "createdAt", "time", "date"]) or ""


def _extract_tool_records(rec: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for key in ("tool_calls", "toolCalls", "tools", "function_calls", "actions"):
        val = rec.get(key)
        if isinstance(val, list):
            out.extend([v for v in val if isinstance(v, dict)])
    content = rec.get("content")
    if isinstance(content, list):
        out.extend([b for b in content if isinstance(b, dict) and _record_role(b) == "tool"])
    return out


def _canonical_tool_name(name: str) -> str:
    raw = (name or "Tool").strip()
    low = raw.lower().replace("-", "_")
    mapping = {
        "edit": "Edit", "apply_patch": "Edit", "insert_edit_into_file": "Edit", "replace_in_file": "Edit",
        "write": "Write", "write_file": "Write", "create_file": "Write",
        "read": "Read", "read_file": "Read", "open_file": "Read",
        "grep": "Search", "grep_search": "Search", "search": "Search", "file_search": "Search",
        "ls": "LS", "list_files": "LS", "glob": "Glob",
        "bash": "Bash", "shell": "Bash", "run_command": "Bash", "terminal": "Bash",
    }
    return mapping.get(low, raw[:1].upper() + raw[1:] if raw else "Tool")


def _first_string(records: Iterable[dict[str, Any]], keys: list[str]) -> str:
    for rec in records:
        for key in keys:
            val = rec.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, dict):
                nested = _first_string([val], keys)
                if nested:
                    return nested
    return ""


def _first_dict(rec: dict[str, Any], keys: list[str]) -> dict[str, Any] | None:
    for key in keys:
        val = rec.get(key)
        if isinstance(val, dict):
            return val
    return None


def _first_int(rec: dict[str, Any], keys: list[str]) -> int:
    for key in keys:
        val = rec.get(key)
        try:
            if val is not None and val != "":
                return int(val)
        except (TypeError, ValueError):
            continue
    return 0


def _truthy_any(rec: dict[str, Any], keys: list[str]) -> bool:
    return any(bool(rec.get(k)) for k in keys)


def _looks_like_usage_record(rec: dict[str, Any]) -> bool:
    return any(k in rec for k in ("usage", "token_usage", "input_tokens", "prompt_tokens", "output_tokens", "completion_tokens"))


def _workspace_from_path(path: Path, base: Path) -> str:
    try:
        rel = path.relative_to(base)
        parts = rel.parts[:-1]
        if parts:
            return str(base / Path(*parts))
    except ValueError:
        pass
    return str(path.parent)


def _safe_id(value: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in value.strip()).strip("-") or "unknown"
