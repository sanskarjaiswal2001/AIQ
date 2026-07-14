import json

from aiq_collector.analyzer import Analyzer
from aiq_collector.parser import ClaudeLogParser


def test_claude_tool_result_feeds_command_quality_metrics(tmp_path):
    project = tmp_path / "-tmp-app"
    project.mkdir()
    path = project / "s.jsonl"
    lines = [
        {"type": "user", "sessionId": "s", "timestamp": "2026-01-01T00:00:00Z", "cwd": "/tmp/app", "message": {"content": "run tests"}},
        {"type": "assistant", "message": {"model": "claude-sonnet-4.6", "usage": {"input_tokens": 10, "output_tokens": 5}, "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "failed", "is_error": True}]}, "toolUseResult": {"stderr": "FAILED", "stdout": "", "interrupted": False}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines))

    session = ClaudeLogParser(claude_dir=str(tmp_path)).parse_file(path, "-tmp-app")
    assert session is not None
    metrics = Analyzer().analyze([session])

    assert metrics["tool_usage"]["failures_by_tool"]["Bash"] == 1
    assert metrics["command_usage"]["by_executable"]["pytest"] == 1
    assert metrics["quality_metrics"]["failed_commands"] == 1
    assert metrics["quality_metrics"]["test_commands"] == 1
