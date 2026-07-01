"""
Claude Code session-log parser.

Reads ``~/.claude/projects/<encoded-project-path>/<session-uuid>.jsonl`` files
and builds :class:`~collector.models.Session` objects containing
:class:`~collector.models.SessionRequest` items.

Each ``.jsonl`` file is one session; each line is a JSON object keyed by
``type``.  Only ``user`` and ``assistant`` lines carry conversation content;
the rest (``last-prompt``, ``permission-mode``, ``attachment``, ``ai-title``,
``file-history-snapshot``, ``system``, ``mode``, ``queue-operation``) are
metadata that inform flags such as *plan mode*, *cancellation*, and *agent
mode*.

Stdlib-only.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import (
    CodeBlock,
    Session,
    SessionRequest,
    ToolUseRecord,
    WRITE_TOOLS,
    READ_FILE_TOOLS,
    READ_PATH_TOOLS,
)

# ---------------------------------------------------------------------------
# Helpers — encoded-path decoding, text extraction, code-block parsing
# ---------------------------------------------------------------------------

# Claude encodes workspace paths by replacing ``/ \ :`` and whitespace with ``-``.
# Unix:  -home-phoenix-myproject  → /home/phoenix/myproject
# Windows: c--dev-project         → C:\dev\project


def decode_workspace_path(encoded: str) -> str:
    """Best-effort decode of an encoded Claude project directory name back to
    a filesystem path.  Returns the original string if decoding is ambiguous.
    """
    if not encoded:
        return encoded

    # Windows drive letter pattern: ``c--dev-project`` → ``C:\dev\project``
    win_match = re.match(r"^([a-zA-Z])--(.+)$", encoded)
    if win_match:
        drive = win_match.group(1).upper()
        rest = win_match.group(2)
        components = rest.split("-")
        # filter empties from consecutive dashes
        components = [c for c in components if c]
        return drive + ":\\" + "\\".join(components)

    # Unix path: leading ``-`` → ``/``
    if encoded.startswith("-"):
        components = [c for c in encoded[1:].split("-") if c]
        return "/" + "/".join(components)

    # Unknown — return as-is
    return encoded


def workspace_name_from_path(path: str) -> str:
    """Extract the last path component as the workspace display name."""
    if not path:
        return "unknown"
    # handle both / and \\ separators
    parts = re.split(r"[\\/]+", path)
    parts = [p for p in parts if p]
    return parts[-1] if parts else path


def workspace_path_from_log_lines(lines: list[dict[str, Any]], encoded_name: str = "") -> str:
    """Return the best workspace path for a Claude session.

    Claude stores a real ``cwd`` on many log records. Prefer that over the
    parent directory's encoded name because the encoded form is lossy: hyphens,
    spaces, path separators, and Windows separators all collapse to ``-``.
    """
    keys = ("cwd", "workspace", "workspace_path", "workspacePath", "project_path", "projectPath", "root")
    for ln in lines:
        for key in keys:
            val = ln.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        msg = ln.get("message")
        if isinstance(msg, dict):
            for key in keys:
                val = msg.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return decode_workspace_path(encoded_name)


# ---------------------------------------------------------------------------
# Text + content extraction
# ---------------------------------------------------------------------------

# Prefixes that mark non-real user prompts (slash-command wrappers, cancels)
_SKIP_PREFIXES: tuple[str, ...] = (
    "<command-",
    "<local-command-",
    "[Request interrupted",
)


def _extract_user_text(content: Any) -> str | None:
    """Extract real user prompt text from a ``user`` line's ``message.content``.

    Returns ``None`` when the line is a tool-result array or a skipped wrapper.
    Returns the text string for real prompts.
    """
    if isinstance(content, str):
        stripped = content.strip()
        if not stripped:
            return None
        for prefix in _SKIP_PREFIXES:
            if stripped.startswith(prefix):
                return None
        return content

    # Array of content blocks → tool results, not a real prompt
    if isinstance(content, list):
        return None

    return None


def _extract_assistant_text(content: Any) -> tuple[str, list[dict]]:
    """Extract concatenated text and a list of content-block dicts from an
    assistant ``message.content`` array.  Returns ``(text, blocks)``.
    """
    if isinstance(content, str):
        return content, []
    if not isinstance(content, list):
        return "", []
    parts: list[str] = []
    blocks: list[dict] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif btype == "thinking" and isinstance(block.get("thinking"), str):
            # thinking text is included for completeness but tagged
            parts.append(block["thinking"])
        blocks.append(block)
    return "\n".join(parts), blocks


# ---------------------------------------------------------------------------
# Code-block extraction (markdown fences + Write/Edit tool inputs)
# ---------------------------------------------------------------------------

# Matches ```lang\n ... ``` fences (non-greedy)
_CODE_FENCE_RE = re.compile(r"```([\w+-]*)\n(.*?)```", re.DOTALL)

# Map file extensions → language label for tool-input code
_EXT_LANG: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "tsx",
    ".jsx": "jsx", ".java": "java", ".go": "go", ".rs": "rust", ".rb": "ruby",
    ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp",
    ".cs": "csharp", ".swift": "swift", ".kt": "kotlin", ".scala": "scala",
    ".sh": "bash", ".bash": "bash", ".zsh": "bash", ".fish": "bash",
    ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".xml": "xml",
    ".html": "html", ".css": "css", ".scss": "scss", ".sql": "sql",
    ".md": "markdown", ".toml": "toml", ".ini": "ini", ".cfg": "ini",
    ".scad": "openscad", ".lua": "lua", ".r": "r", ".pl": "perl",
    ".dart": "dart", ".ex": "elixir", ".exs": "elixir", ".clj": "clojure",
    ".vim": "vim", ".dockerfile": "dockerfile",
}


def _lang_from_path(file_path: str) -> str:
    """Guess a language label from a file path's extension."""
    if not file_path:
        return ""
    ext = os.path.splitext(file_path)[1].lower()
    if not ext:
        # filename-only specials like "Dockerfile", "Makefile"
        base = os.path.basename(file_path).lower()
        if base == "dockerfile":
            return "dockerfile"
        if base in ("makefile", "gnumakefile"):
            return "makefile"
        return ""
    return _EXT_LANG.get(ext, ext.lstrip("."))


def _count_loc(code: str) -> int:
    """Count non-blank lines in a code string."""
    if not code:
        return 0
    return sum(1 for line in code.splitlines() if line.strip())


def extract_code_blocks_from_text(text: str) -> list[CodeBlock]:
    """Extract code blocks from markdown ``` fences in response text."""
    blocks: list[CodeBlock] = []
    if not text:
        return blocks
    for m in _CODE_FENCE_RE.finditer(text):
        lang = m.group(1).strip() or "text"
        code = m.group(2)
        blocks.append(CodeBlock(
            language=lang,
            loc=_count_loc(code),
            source="text",
        ))
    return blocks


def extract_code_from_tool(name: str, inp: dict[str, Any]) -> list[CodeBlock]:
    """Extract code blocks from Write/Edit tool inputs.

    Write  → ``input.content``
    Edit   → ``input.new_str`` OR ``input.new_string`` (real logs use new_string)
    MultiEdit → list of edits, each with ``new_str`` / ``new_string``
    """
    blocks: list[CodeBlock] = []
    if name == "Write":
        content = inp.get("content")
        if isinstance(content, str) and content.strip():
            fp = inp.get("file_path", "")
            blocks.append(CodeBlock(
                language=_lang_from_path(fp),
                loc=_count_loc(content),
                source="write",
                file_path=fp,
            ))
    elif name in ("Edit", "MultiEditTool", "MultiEdit"):
        fp = inp.get("file_path", "")
        # Edit: single new_str / new_string
        new_str = inp.get("new_str") or inp.get("new_string")
        if isinstance(new_str, str) and new_str.strip():
            blocks.append(CodeBlock(
                language=_lang_from_path(fp),
                loc=_count_loc(new_str),
                source="edit",
                file_path=fp,
            ))
        # MultiEdit: edits is a list of {old_string/new_string}
        edits = inp.get("edits")
        if isinstance(edits, list):
            for ed in edits:
                if isinstance(ed, dict):
                    ns = ed.get("new_str") or ed.get("new_string")
                    if isinstance(ns, str) and ns.strip():
                        blocks.append(CodeBlock(
                            language=_lang_from_path(fp),
                            loc=_count_loc(ns),
                            source="edit",
                            file_path=fp,
                        ))
    return blocks


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------


def _extract_usage(message: dict[str, Any]) -> tuple[int, int, int, int]:
    """Return (input, output, cache_read, cache_write) token counts from an
    assistant ``message.usage`` block.
    """
    usage = message.get("usage") or {}
    inp = usage.get("input_tokens", 0) or 0
    out = usage.get("output_tokens", 0) or 0
    cache_read = usage.get("cache_read_input_tokens", 0) or 0
    cache_write = usage.get("cache_creation_input_tokens", 0) or 0
    return int(inp), int(out), int(cache_read), int(cache_write)


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------


class ClaudeLogParser:
    """Parses Claude Code ``.jsonl`` session files into :class:`Session` objects.

    Usage::

        parser = ClaudeLogParser()
        sessions = parser.parse_directory("~/.claude/projects")
        # or
        session = parser.parse_file("/path/to/session.jsonl")
    """

    def __init__(self, claude_dir: str | Path | None = None) -> None:
        if claude_dir is None:
            claude_dir = os.path.expanduser("~/.claude/projects")
        self.claude_dir = Path(claude_dir)

    # -- public API ---------------------------------------------------------

    def parse_directory(self, claude_dir: str | Path | None = None) -> list[Session]:
        """Parse every ``.jsonl`` session file under ``claude_dir`` (or the
        directory given at construction).  Returns a list of non-empty sessions.
        """
        base = Path(claude_dir) if claude_dir else self.claude_dir
        if not base.is_dir():
            return []

        sessions: list[Session] = []
        for project_dir in sorted(base.iterdir()):
            if not project_dir.is_dir():
                continue
            encoded_name = project_dir.name
            for jsonl in sorted(project_dir.glob("*.jsonl")):
                session = self.parse_file(jsonl, encoded_name)
                if session and session.requests:
                    sessions.append(session)
        return sessions

    def parse_file(self, path: str | Path, encoded_name: str = "") -> Session | None:
        """Parse a single ``.jsonl`` session file.  Returns ``None`` for empty
        or unreadable files.  ``encoded_name`` is the parent directory name
        (used for workspace decoding) — derived from path if not supplied.
        """
        path = Path(path)
        if not path.is_file():
            return None
        if not encoded_name:
            encoded_name = path.parent.name

        # Read all lines, tolerating malformed JSON
        raw_lines: list[dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(obj, dict):
                        raw_lines.append(obj)
        except OSError:
            return None

        return self._build_session(raw_lines, encoded_name, path.stem)

    # -- internal: session construction ------------------------------------

    def _build_session(
        self,
        lines: list[dict[str, Any]],
        encoded_name: str,
        fallback_id: str,
    ) -> Session | None:
        """Construct a :class:`Session` from parsed JSON lines."""
        if not lines:
            return None

        session = Session()
        ws_path = workspace_path_from_log_lines(lines, encoded_name)
        session.workspace_path = ws_path
        session.workspace_name = workspace_name_from_path(ws_path)
        session.workspace_id = f"claude-{encoded_name}"

        # First line usually has sessionId
        for ln in lines:
            sid = ln.get("sessionId")
            if sid:
                session.session_id = sid
                break
        if not session.session_id:
            session.session_id = fallback_id

        # Pass 1 — collect session-level metadata (mode, system subtypes, etc.)
        self._collect_session_meta(lines, session)

        # Pass 2 — walk user/assistant lines → requests
        requests = self._build_requests(lines)
        if not requests:
            return None
        session.requests = requests

        # Timestamps
        timestamps = [r.timestamp for r in requests if r.timestamp]
        if timestamps:
            session.creation_date = timestamps[0]
            session.last_message_date = timestamps[-1]

        # Collect all models used
        for r in requests:
            for m in r.models:
                if m and m != "<synthetic>":
                    session.models.add(m)

        # Aggregate session-level flags from requests
        session.has_plan_mode = any(r.is_plan_mode for r in requests)
        session.has_subagents = any(r.has_subagents for r in requests)
        session.has_skills = any(r.has_skills for r in requests)
        session.has_mcp = any(r.has_mcp for r in requests)

        return session

    # -- internal: session metadata ---------------------------------------

    def _collect_session_meta(self, lines: list[dict[str, Any]], session: Session) -> None:
        """Scan metadata lines for session-level context: version, git branch,
        plan-mode transitions, etc.
        """
        plan_mode_active = False
        for ln in lines:
            ltype = ln.get("type")

            # version / gitBranch appear on user + assistant lines
            if not session.version:
                session.version = ln.get("version", "") or ""
            if not session.git_branch:
                session.git_branch = ln.get("gitBranch", "") or ""

            # mode lines: { "type": "mode", "mode": "plan" | "normal", ... }
            if ltype == "mode":
                mode_val = ln.get("mode", "")
                if mode_val == "plan":
                    plan_mode_active = True
                elif mode_val == "normal":
                    plan_mode_active = False

        # store plan-mode as a session flag; per-request flags set in _build_requests
        session._plan_mode_active = plan_mode_active  # type: ignore[attr-defined]

    # -- internal: request construction -----------------------------------

    def _build_requests(self, lines: list[dict[str, Any]]) -> list[SessionRequest]:
        """Walk user/assistant lines and group them into requests.

        A *request* = one real user prompt + all assistant lines that follow
        until the next real user prompt.
        """
        requests: list[SessionRequest] = []
        current: SessionRequest | None = None
        plan_mode_active = False

        # Track per-session plan mode transitions from `mode` lines.
        # We re-scan here so we can set per-request flags in order.
        for ln in lines:
            ltype = ln.get("type")

            # mode transitions
            if ltype == "mode":
                mode_val = ln.get("mode", "")
                if mode_val == "plan":
                    plan_mode_active = True
                elif mode_val == "normal":
                    plan_mode_active = False
                continue

            # Skip metadata-only line types
            if ltype not in ("user", "assistant"):
                continue

            if ltype == "user":
                msg = ln.get("message") or {}
                content = msg.get("content")
                text = _extract_user_text(content)
                if text is None:
                    # tool-result array or skipped wrapper — attach cancellation
                    # marker if applicable, but don't start a new request
                    if current and isinstance(content, str):
                        if content.strip().startswith("[Request interrupted"):
                            current.is_canceled = True
                    # also detect isApiErrorMessage → canceled
                    if current and ln.get("isApiErrorMessage"):
                        current.is_canceled = True
                    continue

                # Start a new request
                current = SessionRequest(
                    message=text,
                    message_length=len(text),
                    timestamp=ln.get("timestamp", "") or "",
                    is_plan_mode=plan_mode_active,
                )
                # parse timestamp
                current.timestamp_dt = _parse_iso(ln.get("timestamp"))
                requests.append(current)

            elif ltype == "assistant":
                if current is None:
                    # assistant before any user prompt — skip
                    continue
                self._accumulate_assistant(ln, current)

        # Compute elapsed time between consecutive requests
        for i, req in enumerate(requests):
            if i + 1 < len(requests):
                nxt = requests[i + 1]
                if req.timestamp_dt and nxt.timestamp_dt:
                    delta = (nxt.timestamp_dt - req.timestamp_dt).total_seconds()
                    req.elapsed_ms = int(delta * 1000)
            else:
                # last request: use system turn_duration if available
                req.elapsed_ms = 0

        return requests

    # -- internal: assistant accumulation --------------------------------

    def _accumulate_assistant(self, ln: dict[str, Any], req: SessionRequest) -> None:
        """Accumulate tokens, tools, text, files, and code from one assistant
        line into the current request.
        """
        message = ln.get("message") or {}
        model = message.get("model", "") or ""
        if model and model != "<synthetic>":
            if model not in req.models:
                req.models.append(model)
            if not req.model:
                req.model = model

        # tokens
        inp, out, cr, cw = _extract_usage(message)
        req.input_tokens += inp + cr + cw   # total input = base + cache read + cache write
        req.output_tokens += out
        req.cache_read_tokens += cr
        req.cache_write_tokens += cw

        # content blocks
        text, blocks = _extract_assistant_text(message.get("content"))
        if text:
            req.response_text += ("\n" + text) if req.response_text else text

        # code blocks from response text
        for cb in extract_code_blocks_from_text(text):
            req.code_blocks.append(cb)

        # tool_use blocks
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") != "tool_use":
                continue
            name = block.get("name", "") or ""
            inp_data = block.get("input") or {}
            if not isinstance(inp_data, dict):
                inp_data = {}
            tool = ToolUseRecord(name=name, input=inp_data)
            self._classify_tool(tool, req)
            req.tools_used.append(tool)

            # code blocks from tool inputs
            for cb in extract_code_from_tool(name, inp_data):
                req.code_blocks.append(cb)

        # MCP / subagent / skill detection at request level
        for t in req.tools_used:
            if "mcp_" in t.name.lower():
                req.has_mcp = True
            if t.is_skill_tool:
                req.has_skills = True
        # subagent detection: Task tool or sidechain lines
        if any(t.name in ("Task", "SubAgent") for t in req.tools_used):
            req.has_subagents = True
        if ln.get("isSidechain"):
            req.has_subagents = True

    # -- internal: tool classification -----------------------------------

    def _classify_tool(self, tool: ToolUseRecord, req: SessionRequest) -> None:
        """Classify a tool use and populate file lists on the request."""
        inp = tool.input

        # extract file_path / path
        fp = inp.get("file_path") or inp.get("path") or inp.get("pattern") or ""
        if isinstance(fp, str):
            tool.file_path = fp
        else:
            tool.file_path = ""

        if tool.is_write_tool:
            if tool.file_path:
                req.edited_files.append(tool.file_path)
        elif tool.is_read_file_tool:
            if tool.file_path:
                req.referenced_files.append(tool.file_path)
        elif tool.is_read_path_tool:
            if tool.file_path:
                req.referenced_files.append(tool.file_path)
        elif tool.is_skill_tool:
            skill_name = inp.get("skill") or inp.get("skill_name") or ""
            if isinstance(skill_name, str) and skill_name:
                req.skills_used.append(skill_name)


# ---------------------------------------------------------------------------
# Utility — ISO timestamp parsing
# ---------------------------------------------------------------------------


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp (Claude format: ``…Z``) to a timezone-aware
    :class:`datetime`.  Returns ``None`` on failure.
    """
    if not ts:
        return None
    try:
        # Claude uses ``2026-05-22T03:40:07.810Z`` — fromisoformat needs +00:00
        s = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
