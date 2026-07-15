#!/usr/bin/env python3
"""
test_collector.py — test suite for the AI-Engineering-Coach edge collector.

Tests the parser, rules, scoring, and analyzer against:
  1. Synthetic test data (edge cases)
  2. Real Claude logs on this machine

Run:  python3 -m pytest test_collector.py     (if pytest available)
  or:  python3 test_collector.py              (standalone)
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

# Bootstrap package imports
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from aiq_collector.parser import (
    ClaudeLogParser,
    decode_workspace_path,
    workspace_name_from_path,
    extract_code_blocks_from_text,
    extract_code_from_tool,
)
from aiq_collector.models import Session, SessionRequest, CodeBlock, ToolUseRecord
from aiq_collector.rules import run_all_rules, RULE_REGISTRY
from aiq_collector.scoring import (
    model_tier,
    normalize_model_id,
    estimate_request_cost,
    compute_practice_scores,
    aggregate_model_usage,
)
from aiq_collector.analyzer import Analyzer, classify_work_type
from aiq_collector.collect import collect_metrics
from aiq_collector.harnesses import GenericJsonAgentParser, HarnessSpec, collect_sessions


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _make_user_line(content, timestamp="2026-06-01T10:00:00.000Z", sid="test-session"):
    """Build a user line dict."""
    return {
        "type": "user",
        "message": {"role": "user", "content": content},
        "uuid": "u1", "timestamp": timestamp,
        "sessionId": sid,
        "version": "2.1.141", "gitBranch": "main",
    }


def _make_assistant_line(content_blocks, model="claude-sonnet-4-6",
                         usage=None, timestamp="2026-06-01T10:00:05.000Z",
                         sid="test-session"):
    """Build an assistant line dict."""
    if usage is None:
        usage = {"input_tokens": 10, "output_tokens": 100,
                 "cache_read_input_tokens": 500, "cache_creation_input_tokens": 200}
    return {
        "type": "assistant",
        "message": {
            "model": model,
            "content": content_blocks,
            "usage": usage,
        },
        "uuid": "a1", "timestamp": timestamp,
        "sessionId": sid,
    }


def _write_session_jsonl(path, lines):
    """Write a list of line dicts to a .jsonl file."""
    with open(path, "w") as f:
        for ln in lines:
            f.write(json.dumps(ln) + "\n")


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------

class TestPathDecoding:
    def test_unix_path(self):
        assert decode_workspace_path("-home-phoenix-myproject") == "/home/phoenix/myproject"

    def test_unix_root(self):
        assert decode_workspace_path("-home") == "/home"

    def test_windows_path(self):
        assert decode_workspace_path("c--dev-project") == "C:\\dev\\project"

    def test_unknown_returns_as_is(self):
        assert decode_workspace_path("myproject") == "myproject"

    def test_workspace_name_unix(self):
        assert workspace_name_from_path("/home/phoenix/myproject") == "myproject"

    def test_workspace_name_windows(self):
        assert workspace_name_from_path("C:\\dev\\project") == "project"

    def test_workspace_name_empty(self):
        assert workspace_name_from_path("") == "unknown"


class TestCodeExtraction:
    def test_text_code_block(self):
        text = "Here is code:\n```python\nprint('hello')\nprint('world')\n```\nDone."
        blocks = extract_code_blocks_from_text(text)
        assert len(blocks) == 1
        assert blocks[0].language == "python"
        assert blocks[0].loc == 2
        assert blocks[0].source == "text"

    def test_text_multiple_blocks(self):
        text = "```js\nfoo()\n```\nand\n```py\nbar()\n```"
        blocks = extract_code_blocks_from_text(text)
        assert len(blocks) == 2

    def test_text_no_code(self):
        assert extract_code_blocks_from_text("just text") == []

    def test_write_tool_extraction(self):
        blocks = extract_code_from_tool("Write", {
            "file_path": "/app/main.py",
            "content": "import os\nprint(os.getcwd())\n",
        })
        assert len(blocks) == 1
        assert blocks[0].language == "python"
        assert blocks[0].loc == 2
        assert blocks[0].source == "write"
        assert blocks[0].file_path == "/app/main.py"

    def test_edit_tool_new_string(self):
        """Real Claude logs use 'new_string' not 'new_str'."""
        blocks = extract_code_from_tool("Edit", {
            "file_path": "/app/config.yaml",
            "old_string": "old",
            "new_string": "new: value\nkey: val\n",
        })
        assert len(blocks) == 1
        assert blocks[0].loc == 2
        assert blocks[0].source == "edit"

    def test_edit_tool_new_str_fallback(self):
        """Also support the spec's 'new_str' field name."""
        blocks = extract_code_from_tool("Edit", {
            "file_path": "/app/config.yaml",
            "old_string": "old",
            "new_str": "new line\n",
        })
        assert len(blocks) == 1
        assert blocks[0].loc == 1


class TestParser:
    def test_parse_simple_session(self, tmp_path):
        """Parse a session with one user prompt and one assistant response."""
        project_dir = tmp_path / "-home-user-app"
        project_dir.mkdir()
        jsonl = project_dir / "abc123.jsonl"

        lines = [
            _make_user_line("Fix the bug in auth.py", timestamp="2026-06-01T10:00:00Z"),
            _make_assistant_line([
                {"type": "text", "text": "I'll fix it."},
                {"type": "tool_use", "name": "Edit", "id": "t1",
                 "input": {"file_path": "/app/auth.py", "old_string": "x",
                           "new_string": "y\nz\n"}},
            ]),
            _make_assistant_line([
                {"type": "text", "text": "Done:\n```python\ndef auth():\n    pass\n```"},
            ], usage={"input_tokens": 5, "output_tokens": 50,
                      "cache_read_input_tokens": 1000, "cache_creation_input_tokens": 500}),
        ]
        _write_session_jsonl(jsonl, lines)

        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert len(sessions) == 1
        s = sessions[0]
        assert s.session_id == "test-session"
        assert s.workspace_name == "app"
        assert s.workspace_id == "claude--home-user-app"
        assert len(s.requests) == 1
        r = s.requests[0]
        assert r.message == "Fix the bug in auth.py"
        assert r.message_length == len("Fix the bug in auth.py")  # 22
        assert r.model == "claude-sonnet-4-6"
        assert len(r.tools_used) == 1
        assert r.tools_used[0].name == "Edit"
        assert r.edited_files == ["/app/auth.py"]
        # tokens accumulated across both assistant lines:
        # line 1: input(10) + cache_read(500) + cache_write(200) = 710
        # line 2: input(5) + cache_read(1000) + cache_write(500) = 1505
        # total = 2215
        assert r.input_tokens == (10 + 500 + 200) + (5 + 1000 + 500)
        assert r.output_tokens == 100 + 50
        # code blocks: 1 from Edit tool + 1 from text fence
        assert r.ai_loc == 2 + 2  # 2 from edit, 2 from text

    def test_parse_prefers_real_cwd_over_lossy_encoded_project_dir(self, tmp_path):
        """Claude logs include cwd; use it because encoded folder names are lossy on office machines."""
        project_dir = tmp_path / "-Users-office-Work-Finance-App"
        project_dir.mkdir()
        jsonl = project_dir / "office.jsonl"
        lines = [
            _make_user_line("Implement budget report", sid="office-session"),
            _make_assistant_line([{"type": "text", "text": "Done"}], sid="office-session"),
        ]
        lines[0]["cwd"] = "/Users/office/Work/finance-app"
        _write_session_jsonl(jsonl, lines)

        sessions = ClaudeLogParser(claude_dir=str(tmp_path)).parse_directory()
        assert len(sessions) == 1
        assert sessions[0].workspace_path == "/Users/office/Work/finance-app"
        assert sessions[0].workspace_name == "finance-app"

    def test_skip_tool_result_arrays(self, tmp_path):
        """User lines with array content (tool results) should not start new requests."""
        project_dir = tmp_path / "-home-user-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"

        lines = [
            _make_user_line("First prompt"),
            _make_assistant_line([
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "ls"}},
            ]),
            # tool result — should NOT start a new request
            _make_user_line([
                {"type": "tool_result", "tool_use_id": "t1", "content": "file1\nfile2", "is_error": False}
            ]),
            _make_assistant_line([{"type": "text", "text": "result"}]),
            # second real prompt
            _make_user_line("Second prompt", timestamp="2026-06-01T11:00:00Z"),
        ]
        _write_session_jsonl(jsonl, lines)

        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert len(sessions) == 1
        assert len(sessions[0].requests) == 2  # only 2 real prompts

    def test_tool_use_result_as_list_does_not_crash(self, tmp_path):
        """toolUseResult is sometimes a list (e.g. multi-block tool output), not a dict."""
        project_dir = tmp_path / "-home-user-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"

        lines = [
            _make_user_line("First prompt"),
            _make_assistant_line([
                {"type": "tool_use", "name": "Bash", "id": "t1", "input": {"command": "ls"}},
            ]),
            {
                "type": "user",
                "message": {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": "file1\nfile2", "is_error": False}
                ]},
                "toolUseResult": ["file1", "file2"],
                "uuid": "u2", "timestamp": "2026-06-01T10:05:00Z",
                "sessionId": "test-session", "version": "2.1.141", "gitBranch": "main",
            },
        ]
        _write_session_jsonl(jsonl, lines)

        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert len(sessions) == 1

    def test_skip_command_wrappers(self, tmp_path):
        """Lines starting with <command- or <local-command- should be skipped."""
        project_dir = tmp_path / "-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"

        lines = [
            _make_user_line("<command-name>help</command-name>"),
            _make_user_line("<local-command-stdout>output</local-command-stdout>"),
            _make_user_line("Real prompt"),
        ]
        _write_session_jsonl(jsonl, lines)

        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert len(sessions[0].requests) == 1
        assert sessions[0].requests[0].message == "Real prompt"

    def test_skip_interrupted(self, tmp_path):
        """Lines starting with [Request interrupted should be skipped."""
        project_dir = tmp_path / "-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"
        lines = [
            _make_user_line("Real prompt"),
            _make_user_line("[Request interrupted by user]"),
        ]
        _write_session_jsonl(jsonl, lines)
        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert len(sessions[0].requests) == 1

    def test_malformed_json_skipped(self, tmp_path):
        """Malformed JSON lines should be silently skipped."""
        project_dir = tmp_path / "-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"
        with open(jsonl, "w") as f:
            f.write("not json at all\n")
            f.write("{ broken json\n")
            f.write(json.dumps(_make_user_line("Good prompt")) + "\n")
        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert len(sessions) == 1
        assert len(sessions[0].requests) == 1

    def test_empty_session_skipped(self, tmp_path):
        """Sessions with no real prompts should be skipped (return None)."""
        project_dir = tmp_path / "-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"
        with open(jsonl, "w") as f:
            f.write(json.dumps({"type": "last-prompt", "sessionId": "x"}) + "\n")
        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert sessions == []

    def test_plan_mode_detection(self, tmp_path):
        """Plan mode lines should set is_plan_mode on subsequent requests."""
        project_dir = tmp_path / "-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"
        lines = [
            {"type": "mode", "mode": "plan", "sessionId": "s1"},
            _make_user_line("Plan this feature", sid="s1"),
            _make_assistant_line([{"type": "text", "text": "plan"}], sid="s1"),
            {"type": "mode", "mode": "normal", "sessionId": "s1"},
            _make_user_line("Now implement", timestamp="2026-06-01T12:00:00Z", sid="s1"),
        ]
        _write_session_jsonl(jsonl, lines)
        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert sessions[0].has_plan_mode
        assert sessions[0].requests[0].is_plan_mode
        assert not sessions[0].requests[1].is_plan_mode

    def test_elapsed_time(self, tmp_path):
        """Elapsed time between consecutive requests should be computed."""
        project_dir = tmp_path / "-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"
        lines = [
            _make_user_line("First", timestamp="2026-06-01T10:00:00Z"),
            _make_user_line("Second", timestamp="2026-06-01T10:00:10Z"),  # 10s later
        ]
        _write_session_jsonl(jsonl, lines)
        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert sessions[0].requests[0].elapsed_ms == 10_000

    def test_synthetic_model_skipped(self, tmp_path):
        """<synthetic> model should not be counted as a real model."""
        project_dir = tmp_path / "-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"
        lines = [
            _make_user_line("prompt"),
            _make_assistant_line([{"type": "text", "text": "resp"}], model="<synthetic>"),
        ]
        _write_session_jsonl(jsonl, lines)
        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        r = sessions[0].requests[0]
        assert r.model == ""  # synthetic not set as primary model
        assert "<synthetic>" not in sessions[0].models


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------

class TestModelTier:
    def test_claude_sonnet_46(self):
        assert model_tier("claude-sonnet-4-6") == 1

    def test_claude_opus_45(self):
        assert model_tier("claude-opus-4.5") == 3

    def test_claude_opus_47(self):
        assert model_tier("claude-opus-4.7") == 7

    def test_claude_haiku_45(self):
        assert model_tier("claude-haiku-4.5") == 0

    def test_gpt_52(self):
        assert model_tier("gpt-5.2") == 1

    def test_unknown_defaults_tier1(self):
        assert model_tier("some-unknown-model") == 1

    def test_normalize_strips_copilot(self):
        assert normalize_model_id("copilot/claude-sonnet-4-6") == "claude-sonnet-4.6"

    def test_normalize_strips_thought(self):
        assert normalize_model_id("claude-sonnet-4-6-thought") == "claude-sonnet-4.6"

    def test_normalize_strips_date(self):
        assert normalize_model_id("claude-sonnet-4-6-20260601") == "claude-sonnet-4.6"

    def test_normalize_converts_hyphenated(self):
        assert normalize_model_id("claude-sonnet-4-6") == "claude-sonnet-4.6"


class TestCostEstimation:
    def test_sonnet_cost(self):
        req = SessionRequest(
            model="claude-sonnet-4-6",
            input_tokens=12152,  # 10000 base + 2000 cache_read + 152 cache_write... let's be explicit
            cache_read_tokens=2000,
            cache_write_tokens=152,
            output_tokens=100,
        )
        # Recalculate: base = 12152 - 2000 - 152 = 10000
        # cost = 10000/1M * 3.00 + 2000/1M * 0.30 + 100/1M * 15.00 + 152/1M * 3.75
        expected = (10000 / 1e6 * 3.00 + 2000 / 1e6 * 0.30
                    + 100 / 1e6 * 15.00 + 152 / 1e6 * 3.75)
        assert abs(estimate_request_cost(req) - round(expected, 6)) < 0.0001

    def test_synthetic_zero_cost(self):
        req = SessionRequest(model="<synthetic>", input_tokens=100, output_tokens=50)
        assert estimate_request_cost(req) == 0.0


class TestPracticeScores:
    def test_empty_sessions(self):
        scores = compute_practice_scores([])
        assert len(scores) == 5
        for g in scores.values():
            assert g["score"] == 100  # no penalties, no requests → 100

    def test_perfect_score(self):
        """A request with good practices should yield high scores."""
        req = SessionRequest(
            message="Please implement the authentication module with JWT tokens. "
                    "Must ensure the auth.py file handles token expiry.",
            message_length=100,
            timestamp_dt=datetime(2026, 6, 1, 14, 0, 0, tzinfo=timezone.utc),  # 2pm weekday
            edited_files=["auth.py"],
            referenced_files=["auth.py"],
        )
        req.tools_used = [type("T", (), {"name": "Edit"})()]  # has tools
        s = Session(requests=[req])
        scores = compute_practice_scores([s])
        # prompt-quality: message > 30 chars, has file refs → no penalty → 100
        assert scores["prompt-quality"]["score"] == 100
        # session-hygiene: not canceled, 2pm weekday → no penalty → 100
        assert scores["session-hygiene"]["score"] == 100


# ---------------------------------------------------------------------------
# Rules tests
# ---------------------------------------------------------------------------

class TestRules:
    def test_all_20_rules_registered(self):
        assert len(RULE_REGISTRY) == 20

    def test_all_rules_return_detection_result(self):
        results = run_all_rules([])
        assert len(results) == 20
        for r in results:
            assert r.rule_id
            assert r.name
            assert r.group in ("prompt-quality", "code-review", "tool-mastery", "session-hygiene")
            assert r.severity in ("low", "medium", "high")
            assert isinstance(r.triggered, bool)
            assert isinstance(r.occurrences, int)
            assert isinstance(r.total, int)
            assert isinstance(r.examples, list)

    def test_lazy_prompting_triggers(self):
        """20 short prompts out of 30 → ratio 0.67 > 0.3, count 20 > 10."""
        reqs = [SessionRequest(message="do it", message_length=5) for _ in range(20)]
        reqs += [SessionRequest(message="Please implement the full authentication module with tests", message_length=70) for _ in range(10)]
        s = Session(requests=reqs)
        results = run_all_rules([s])
        lazy = next(r for r in results if r.rule_id == "lazy-prompting")
        assert lazy.triggered
        assert lazy.occurrences == 20

    def test_lazy_prompting_not_triggered_low_ratio(self):
        """5 short out of 67 → ratio 0.07 < 0.3."""
        reqs = [SessionRequest(message="x", message_length=1) for _ in range(5)]
        reqs += [SessionRequest(message="This is a detailed prompt with enough context", message_length=50) for _ in range(62)]
        s = Session(requests=reqs)
        results = run_all_rules([s])
        lazy = next(r for r in results if r.rule_id == "lazy-prompting")
        assert not lazy.triggered

    def test_repeated_prompts_ignores_skill_backed_prompts(self):
        """Reusable skills intentionally repeat templates and should not count as prompt waste."""
        reqs = [
            SessionRequest(message="Use the review skill to inspect this change", message_length=44, has_skills=True, skills_used=["review"])
            for _ in range(8)
        ]
        s = Session(requests=reqs)
        results = run_all_rules([s])
        repeated = next(r for r in results if r.rule_id == "repeated-prompts")
        assert not repeated.triggered
        assert repeated.occurrences == 0

    def test_premium_waste_does_not_flag_short_complex_frontier_turns(self):
        """Short steering on a frontier model can be efficient when context/tools are doing work."""
        reqs = []
        for _ in range(12):
            req = SessionRequest(
                message="continue",
                message_length=8,
                model="claude-opus-4.7",
                input_tokens=6000,
                output_tokens=700,
                edited_files=["app.py"],
            )
            req.code_blocks = [CodeBlock(language="python", loc=1)] * 30
            reqs.append(req)
        results = run_all_rules([Session(requests=reqs)])
        waste = next(r for r in results if r.rule_id == "premium-waste")
        assert not waste.triggered
        assert waste.occurrences == 0

    def test_premium_waste_still_flags_trivial_chatter(self):
        reqs = [SessionRequest(message="thanks", message_length=6, model="claude-opus-4.7") for _ in range(12)]
        results = run_all_rules([Session(requests=reqs)])
        waste = next(r for r in results if r.rule_id == "premium-waste")
        assert waste.triggered
        assert waste.occurrences == 12

    def test_premium_lookup_does_not_flag_contextual_debugging(self):
        reqs = []
        for _ in range(12):
            req = SessionRequest(
                message="why does auth fail? debug server/main.py",
                message_length=40,
                model="gpt-5.2",
                referenced_files=["server/main.py"],
            )
            req.tools_used = [ToolUseRecord(name="Read"), ToolUseRecord(name="Bash")]
            reqs.append(req)
        results = run_all_rules([Session(requests=reqs)])
        lookup = next(r for r in results if r.rule_id == "premium-for-lookup-questions")
        assert not lookup.triggered
        assert lookup.occurrences == 0

    def test_mega_sessions_triggers(self):
        s = Session(requests=[SessionRequest() for _ in range(55)])
        results = run_all_rules([s])
        mega = next(r for r in results if r.rule_id == "mega-sessions")
        assert mega.triggered
        assert mega.occurrences == 1

    def test_session_drift_triggers(self):
        s = Session(requests=[SessionRequest() for _ in range(35)])
        results = run_all_rules([s])
        drift = next(r for r in results if r.rule_id == "session-drift")
        assert drift.triggered

    def test_model_overreliance_triggers(self):
        reqs = [SessionRequest(model="claude-sonnet-4-6") for _ in range(50)]
        s = Session(requests=reqs)
        results = run_all_rules([s])
        over = next(r for r in results if r.rule_id == "model-overreliance")
        assert over.triggered

    def test_frustration_signals_triggers(self):
        reqs = [
            SessionRequest(message="why is this not working!!!", message_length=30),
            SessionRequest(message="wtf is going on here", message_length=22),
            SessionRequest(message="this is wrong again ???", message_length=25),
        ]
        s = Session(requests=reqs)
        results = run_all_rules([s])
        frustr = next(r for r in results if r.rule_id == "frustration-signals")
        assert frustr.triggered
        assert frustr.occurrences == 3

    def test_tunnel_vision_triggers(self):
        sessions = [Session(workspace_name="proj") for _ in range(10)]
        sessions.append(Session(workspace_name="other"))
        results = run_all_rules(sessions)
        tv = next(r for r in results if r.rule_id == "tunnel-vision")
        assert tv.triggered  # 10/11 = 0.909 > 0.9

    def test_late_night_coding_triggers(self):
        reqs = [
            SessionRequest(timestamp_dt=datetime(2026, 6, 1, 23, 0, tzinfo=timezone.utc)),
            SessionRequest(timestamp_dt=datetime(2026, 6, 2, 2, 0, tzinfo=timezone.utc)),
            SessionRequest(timestamp_dt=datetime(2026, 6, 3, 3, 0, tzinfo=timezone.utc)),
        ]
        s = Session(requests=reqs)
        results = run_all_rules([s])
        late = next(r for r in results if r.rule_id == "late-night-coding")
        assert late.triggered
        assert late.occurrences == 3

    def test_weekend_overwork_triggers(self):
        # 2026-06-06 is Saturday, 2026-06-07 is Sunday
        reqs = [
            SessionRequest(timestamp_dt=datetime(2026, 6, 6, 10, 0, tzinfo=timezone.utc)),
            SessionRequest(timestamp_dt=datetime(2026, 6, 7, 14, 0, tzinfo=timezone.utc)),
            SessionRequest(timestamp_dt=datetime(2026, 6, 7, 16, 0, tzinfo=timezone.utc)),
        ]
        s = Session(requests=reqs)
        results = run_all_rules([s])
        weekend = next(r for r in results if r.rule_id == "weekend-overwork")
        assert weekend.triggered
        assert weekend.occurrences == 3

    def test_speed_accept_triggers(self):
        """Adjacent pairs with 20+ LOC and next msg < 15s."""
        reqs = []
        for i in range(6):
            r = SessionRequest(message=f"prompt {i}", message_length=10)
            r.code_blocks = [CodeBlock(loc=25, source="write")]  # 25 LOC
            r.timestamp_dt = datetime(2026, 6, 1, 10, 0, i * 5, tzinfo=timezone.utc)  # 5s apart
            reqs.append(r)
        # set elapsed: each request 5s before next
        for i in range(len(reqs) - 1):
            reqs[i].elapsed_ms = 5000
        s = Session(requests=reqs)
        results = run_all_rules([s])
        speed = next(r for r in results if r.rule_id == "speed-accept")
        assert speed.triggered
        assert speed.occurrences >= 5


# ---------------------------------------------------------------------------
# Analyzer tests
# ---------------------------------------------------------------------------

class TestWorkTypeClassification:
    def test_bug_fix(self):
        assert classify_work_type("fix the login bug") == "bug fix"

    def test_refactor(self):
        assert classify_work_type("refactor the auth module") == "refactor"

    def test_test(self):
        assert classify_work_type("write a test for the parser") == "test"

    def test_feature(self):
        assert classify_work_type("add a new export feature") == "feature"

    def test_config(self):
        assert classify_work_type("update the docker config") == "config"

    def test_other(self):
        assert classify_work_type("hello world") == "other"

    def test_first_match_wins(self):
        # "fix" matches bug fix before "add"
        assert classify_work_type("fix and add the feature") == "bug fix"


class TestAnalyzer:
    def test_full_pipeline(self, tmp_path):
        """End-to-end: parse → analyze → validate JSON structure."""
        project_dir = tmp_path / "-home-user-myapp"
        project_dir.mkdir()
        jsonl = project_dir / "session1.jsonl"

        lines = [
            _make_user_line("Fix the auth bug in login.py. The token validation is broken.",
                            timestamp="2026-06-01T10:00:00Z"),
            _make_assistant_line([
                {"type": "text", "text": "I'll fix the token validation."},
                {"type": "tool_use", "name": "Edit", "id": "t1",
                 "input": {"file_path": "/app/login.py", "old_string": "old",
                           "new_string": "def validate(token):\n    return True\n"}},
            ], timestamp="2026-06-01T10:00:05Z"),
            _make_user_line("Now add tests for it", timestamp="2026-06-01T10:05:00Z"),
            _make_assistant_line([
                {"type": "text", "text": "Here are tests:\n```python\ndef test_validate():\n    assert True\n```"},
            ], timestamp="2026-06-01T10:05:05Z"),
        ]
        _write_session_jsonl(jsonl, lines)

        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        assert len(sessions) == 1

        analyzer = Analyzer()
        metrics = analyzer.analyze(sessions, employee_id="test-user")

        # Validate top-level structure
        assert metrics["employee_id"] == "test-user"
        assert "collected_at" in metrics
        assert "period_start" in metrics
        assert "period_end" in metrics

        # Summary
        assert metrics["summary"]["total_sessions"] == 1
        assert metrics["summary"]["total_requests"] == 2
        assert metrics["summary"]["total_workspaces"] == 1
        assert metrics["summary"]["total_ai_loc"] > 0
        assert metrics["summary"]["total_input_tokens"] > 0
        assert metrics["summary"]["total_output_tokens"] > 0
        assert metrics["summary"]["estimated_cost_usd"] > 0

        # Practice scores — 5 groups
        assert len(metrics["practice_scores"]) == 5
        for g, data in metrics["practice_scores"].items():
            assert 0 <= data["score"] <= 100
            assert isinstance(data["weekly"], list)

        # Anti-patterns — 20 rules
        assert len(metrics["anti_patterns"]) == 20
        for ap in metrics["anti_patterns"]:
            assert "rule_id" in ap
            assert "triggered" in ap
            assert "occurrences" in ap
            assert "examples" in ap

        # Model usage
        assert "claude-sonnet-4.6" in metrics["model_usage"]
        assert metrics["model_usage"]["claude-sonnet-4.6"]["requests"] == 2

        # Work types
        assert "bug fix" in metrics["work_types"]

        # Activity
        assert "daily" in metrics["activity"]
        assert "hourly_heatmap" in metrics["activity"]
        assert "workspaces" in metrics["activity"]
        assert len(metrics["activity"]["hourly_heatmap"]) == 7
        assert len(metrics["activity"]["hourly_heatmap"][0]) == 24
        assert "myapp" in metrics["activity"]["workspaces"]

    def test_empty_sessions_produce_valid_json(self):
        """Analyzer should handle zero sessions gracefully."""
        analyzer = Analyzer()
        metrics = analyzer.analyze([])
        assert metrics["summary"]["total_sessions"] == 0
        assert metrics["summary"]["total_requests"] == 0
        assert len(metrics["anti_patterns"]) == 20
        assert metrics["activity"]["daily"] == {}

    def test_plan_context_adds_rolling_window_rule(self):
        """Billing context should add plan-aware anti-patterns without changing base rule count."""
        req = SessionRequest(
            message="Implement the billing dashboard with tests",
            message_length=42,
            model="claude-sonnet-4-6",
            input_tokens=4_000_000,
            output_tokens=1_000_000,
        )
        metrics = Analyzer().analyze(
            [Session(requests=[req])],
            plan_context={"plan_type": "enterprise_rolling_window", "rolling_window_usd": 25, "rolling_window_days": 30},
        )
        assert metrics["plan_context"]["rolling_window_usd"] == 25
        pressure = next(ap for ap in metrics["anti_patterns"] if ap["rule_id"] == "rolling-window-pressure")
        assert pressure["triggered"]
        assert pressure["metadata"]["utilization"] > 0.85

    def test_project_extraction_groups_by_workspace(self, tmp_path):
        """Sessions from the same workspace path should be grouped into one project."""
        from aiq_collector.analyzer import Analyzer
        from aiq_collector.models import Session, SessionRequest

        # Two sessions in the same project, one in a different project
        sessions = [
            Session(workspace_name="proj-a", workspace_path="/home/user/proj-a", requests=[
                SessionRequest(message="Implement feature X", message_length=20, model="claude-sonnet-4-6", input_tokens=10000, output_tokens=5000),
            ]),
            Session(workspace_name="proj-a", workspace_path="/home/user/proj-a", requests=[
                SessionRequest(message="Fix bug Y", message_length=12, model="claude-sonnet-4-6", input_tokens=8000, output_tokens=3000),
            ]),
            Session(workspace_name="proj-b", workspace_path="/home/user/proj-b", requests=[
                SessionRequest(message="Write tests", message_length=10, model="claude-sonnet-4-6", input_tokens=5000, output_tokens=2000),
            ]),
        ]
        metrics = Analyzer().analyze(sessions)
        projects = metrics["projects"]
        assert len(projects) == 2
        proj_a = next(p for p in projects if p["project_name"] == "proj-a")
        assert proj_a["sessions"] == 2
        assert proj_a["requests"] == 2
        assert proj_a["ai_loc"] >= 0
        # Project IDs should be deterministic
        assert proj_a["project_id"] == Analyzer.project_id_from_path("/home/user/proj-a")
        # Projects sorted by cost descending
        assert projects[0]["estimated_cost_usd"] >= projects[1]["estimated_cost_usd"]

    def test_json_serializable(self, tmp_path):
        """The metrics dict must be fully JSON-serializable."""
        project_dir = tmp_path / "-app"
        project_dir.mkdir()
        jsonl = project_dir / "test.jsonl"
        lines = [
            _make_user_line("test prompt"),
            _make_assistant_line([{"type": "text", "text": "response"}]),
        ]
        _write_session_jsonl(jsonl, lines)
        parser = ClaudeLogParser(claude_dir=str(tmp_path))
        sessions = parser.parse_directory()
        metrics = Analyzer().analyze(sessions)
        # must not raise
        json_str = json.dumps(metrics, ensure_ascii=False, indent=2)
        assert len(json_str) > 0
        # round-trip
        assert json.loads(json_str) == metrics


# ---------------------------------------------------------------------------
# Multi-harness parser tests
# ---------------------------------------------------------------------------

class TestMultiHarness:
    def test_generic_codex_jsonl_parser(self, tmp_path):
        """Codex-style JSONL records should normalize into Session/Request objects."""
        codex_dir = tmp_path / "codex"
        codex_dir.mkdir()
        log = codex_dir / "session.jsonl"
        rows = [
            {"type": "user_message", "content": "Implement billing export", "timestamp": "2026-06-02T10:00:00Z", "cwd": "/repo/aiq", "session_id": "cx1"},
            {"type": "assistant_message", "content": "I'll edit it.", "model": "gpt-5.1-codex", "usage": {"prompt_tokens": 100, "completion_tokens": 50}, "tool_calls": [
                {"name": "apply_patch", "arguments": {"file_path": "/repo/aiq/export.py", "new_string": "def export():\n    return True\n"}}
            ]},
        ]
        _write_session_jsonl(log, rows)
        sessions = GenericJsonAgentParser(HarnessSpec("codex", str(codex_dir), "codex"), codex_dir).parse_directory()
        assert len(sessions) == 1
        s = sessions[0]
        assert s.workspace_id.startswith("codex-")
        assert s.workspace_name == "aiq"
        assert s.requests[0].message == "Implement billing export"
        assert s.requests[0].model == "gpt-5.1-codex"
        assert s.requests[0].input_tokens == 100
        assert s.requests[0].output_tokens == 50
        assert s.requests[0].edited_files == ["/repo/aiq/export.py"]
        assert s.requests[0].ai_loc == 2

    def test_generic_opencode_json_parser(self, tmp_path):
        """OpenCode-style JSON with messages array should parse."""
        opencode_dir = tmp_path / "opencode"
        opencode_dir.mkdir()
        log = opencode_dir / "chat.json"
        log.write_text(json.dumps({
            "id": "oc1",
            "workspacePath": "/work/mobile-app",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "Fix login bug"}], "createdAt": "2026-06-03T11:00:00Z"},
                {"role": "assistant", "content": "Fixed it", "model": "qwen3-coder", "token_usage": {"input_tokens": 90, "output_tokens": 45}, "tools": [
                    {"tool_name": "write_file", "input": {"file_path": "/work/mobile-app/login.ts", "content": "export const ok = true\n"}}
                ]},
            ],
        }), encoding="utf-8")
        sessions = GenericJsonAgentParser(HarnessSpec("opencode", str(opencode_dir), "opencode"), opencode_dir).parse_directory()
        assert len(sessions) == 1
        req = sessions[0].requests[0]
        assert sessions[0].workspace_id.startswith("opencode-")
        assert req.message == "Fix login bug"
        assert req.model == "qwen3-coder"
        assert req.edited_files == ["/work/mobile-app/login.ts"]
        assert req.ai_loc == 1
        assert sessions[0].workspace_path == "/work/mobile-app"
        assert sessions[0].workspace_name == "mobile-app"

    def test_generic_parent_workspace_metadata_survives_flattening(self, tmp_path):
        """Nested JSON logs often put workspace/cwd on the parent object, not each message."""
        root = tmp_path / "cursor"
        root.mkdir()
        log = root / "session.json"
        log.write_text(json.dumps({
            "id": "cur1",
            "cwd": "/Users/office/Client Work/ledger-ui",
            "messages": [
                {"role": "user", "content": "Fix dashboard route", "createdAt": "2026-06-04T09:00:00Z"},
                {"role": "assistant", "content": "Fixed", "model": "cursor-agent", "usage": {"input_tokens": 44, "output_tokens": 12}},
            ],
        }), encoding="utf-8")

        sessions = GenericJsonAgentParser(HarnessSpec("cursor", str(root), "cursor"), root).parse_directory()
        assert len(sessions) == 1
        assert sessions[0].workspace_path == "/Users/office/Client Work/ledger-ui"
        assert sessions[0].workspace_name == "ledger-ui"

    def test_collect_sessions_multiple_harnesses(self, tmp_path):
        claude_root = tmp_path / "claude"
        project_dir = claude_root / "-home-user-web"
        project_dir.mkdir(parents=True)
        _write_session_jsonl(project_dir / "c.jsonl", [
            _make_user_line("Claude prompt", sid="c1"),
            _make_assistant_line([{"type": "text", "text": "ok"}], sid="c1"),
        ])
        codex_root = tmp_path / "codex"
        codex_root.mkdir()
        _write_session_jsonl(codex_root / "x.jsonl", [
            {"type": "user_message", "content": "Codex prompt", "cwd": "/repo/x", "session_id": "x1"},
            {"type": "assistant_message", "content": "ok", "model": "gpt-5.1-codex"},
        ])
        sessions = collect_sessions("claude,codex", dirs={"claude": str(claude_root), "codex": str(codex_root)})
        assert len(sessions) == 2
        assert {s.workspace_id.split("-", 1)[0] for s in sessions} == {"claude", "codex"}

    def test_collect_metrics_harnesses_argument(self, tmp_path):
        codex_root = tmp_path / "codex"
        codex_root.mkdir()
        _write_session_jsonl(codex_root / "x.jsonl", [
            {"type": "user_message", "content": "Add tests", "cwd": "/repo/tests", "session_id": "x1"},
            {"type": "assistant_message", "content": "```python\ndef test_ok():\n    assert True\n```", "model": "gpt-5.1-codex", "usage": {"prompt_tokens": 30, "completion_tokens": 20}},
        ])
        metrics = collect_metrics(harnesses="codex", harness_dirs={"codex": str(codex_root)}, employee_id="multi")
        assert metrics["employee_id"] == "multi"
        assert metrics["summary"]["total_sessions"] == 1
        assert metrics["summary"]["total_requests"] == 1
        assert "gpt-5.1-codex" in metrics["model_usage"]


# ---------------------------------------------------------------------------
# Real logs test
# ---------------------------------------------------------------------------

class TestRealLogs:
    """Tests against the real Claude logs on this machine."""

    CLAUDE_DIR = os.path.expanduser("~/.claude/projects")

    def test_real_logs_parse(self):
        """Parse all real logs and validate metrics structure."""
        if not os.path.isdir(self.CLAUDE_DIR):
            print("    [skipped] no ~/.claude/projects directory")
            return
        parser = ClaudeLogParser(claude_dir=self.CLAUDE_DIR)
        sessions = parser.parse_directory()
        assert len(sessions) > 0, "Expected at least one session from real logs"
        print(f"    ✓ Parsed {len(sessions)} sessions from real logs")
        print(f"    ✓ Total requests: {sum(s.request_count for s in sessions)}")

        # Validate each session has required fields
        for s in sessions:
            assert s.session_id, "Session must have an ID"
            assert s.workspace_name, "Session must have a workspace name"
            assert s.workspace_id.startswith("claude-")
            assert len(s.requests) > 0, "Session must have at least one request"

        # Full analysis
        metrics = Analyzer().analyze(sessions, employee_id="test")
        assert metrics["summary"]["total_sessions"] == len(sessions)
        assert metrics["summary"]["total_requests"] > 0
        assert len(metrics["anti_patterns"]) == 20
        # JSON serializable
        json.dumps(metrics)
        print("    ✓ Full analysis produced valid JSON")
        scores_str = ", ".join(f"{g}={d['score']}" for g, d in metrics["practice_scores"].items())
        print(f"    ✓ Practice scores: {scores_str}")


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------

def _run_all_tests():
    """Simple test runner that doesn't require pytest."""
    import traceback

    classes = [
        TestPathDecoding, TestCodeExtraction, TestParser,
        TestModelTier, TestCostEstimation, TestPracticeScores,
        TestRules, TestWorkTypeClassification, TestAnalyzer,
        TestMultiHarness, TestRealLogs,
    ]

    passed = 0
    failed = 0
    errors = []

    for cls in classes:
        instance = cls()
        test_methods = [m for m in dir(instance) if m.startswith("test_")]
        for method_name in test_methods:
            method = getattr(instance, method_name)
            try:
                # Provide tmp_path fixture if needed
                import inspect
                sig = inspect.signature(method)
                if "tmp_path" in sig.parameters:
                    with tempfile.TemporaryDirectory() as tmp:
                        method(tmp_path=Path(tmp))
                else:
                    method()
                passed += 1
            except AssertionError as e:
                failed += 1
                errors.append((cls.__name__, method_name, str(e)))
                print(f"  ✗ {cls.__name__}.{method_name}: {e}")
            except Exception as e:
                failed += 1
                errors.append((cls.__name__, method_name, traceback.format_exc()))
                print(f"  ✗ {cls.__name__}.{method_name}: {e}")

    print(f"\n{'=' * 60}")
    print(f"  Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'=' * 60}")
    if failed:
        for cls_name, method, err in errors:
            print(f"\n  FAIL: {cls_name}.{method}")
            print(f"  {err[:200]}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(_run_all_tests())
