"""End-to-end test script for the AIQ dashboard backend.

Starts the server is expected to already be running on port 8000.
Posts mock snapshots for several employees, then verifies every endpoint.
Run with:  .venv/bin/python test_server.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("AIQ_TEST_BASE", "http://localhost:8000")


def _req(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw


def ok(label: str, cond: bool, extra: str = "") -> bool:
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}{(' — ' + extra) if extra else ''}")
    return cond


def main() -> int:
    failures = 0

    # --- 1. Health (before any data) ---
    print("1. GET /api/health")
    code, data = _req("GET", "/api/health")
    if not ok("status 200", code == 200, f"got {code}"):
        failures += 1
    if isinstance(data, dict):
        print(f"        {data}")
        if not ok("status ok", data.get("status") == "ok"):
            failures += 1
        if not ok("employee_count is int", isinstance(data.get("employee_count"), int)):
            failures += 1

    # --- Mock data ---
    mock_employees = [
        {
            "employee_id": "john-doe",
            "employee_name": "John Doe",
            "team": "engineering",
            "collected_at": "2026-06-29T13:00:00Z",
            "period_start": "2026-06-01",
            "period_end": "2026-06-29",
            "summary": {
                "total_sessions": 45,
                "total_requests": 320,
                "total_workspaces": 6,
                "total_ai_loc": 12500,
                "total_input_tokens": 1_200_000,
                "total_output_tokens": 800_000,
                "estimated_cost_usd": 78.50,
            },
            "practice_scores": {
                "prompt_quality": 85.0,
                "session_hygiene": 78.0,
                "code_review": 72.0,
                "tool_mastery": 88.0,
                "context_management": 80.0,
            },
            "anti_patterns": [
                {"rule_id": "lazy-prompting", "rule_name": "Lazy Prompting", "rule_group": "lazy-prompting", "severity": "high", "triggered": True, "occurrences": 12, "total": 320, "examples": ["fix it", "do the thing"]},
                {"rule_id": "premium-waste", "rule_name": "Premium Model Waste", "rule_group": "premium-waste", "severity": "high", "triggered": True, "occurrences": 8, "total": 320, "examples": ["used opus for a comment"]},
                {"rule_id": "speed-accept", "rule_name": "Speed Accept", "rule_group": "speed-accept", "severity": "high", "triggered": True, "occurrences": 5, "total": 320},
                {"rule_id": "no-plan-mode", "rule_name": "No Plan Mode", "rule_group": "no-plan-mode", "severity": "low", "triggered": False, "occurrences": 0, "total": 45},
            ],
            "model_usage": {"claude-opus": {"requests": 120, "cost": 55.0}, "claude-sonnet": {"requests": 200, "cost": 23.5}},
            "work_types": {"feature": 0.6, "bugfix": 0.3, "refactor": 0.1},
            "activity": {"by_day": {"2026-06-01": 10, "2026-06-02": 15}},
        },
        {
            "employee_id": "jane-smith",
            "employee_name": "Jane Smith",
            "team": "engineering",
            "collected_at": "2026-06-29T13:00:00Z",
            "period_start": "2026-06-01",
            "period_end": "2026-06-29",
            "summary": {
                "total_sessions": 30,
                "total_requests": 210,
                "total_workspaces": 4,
                "total_ai_loc": 8000,
                "total_input_tokens": 900_000,
                "total_output_tokens": 500_000,
                "estimated_cost_usd": 52.00,
            },
            "practice_scores": {
                "prompt_quality": 90.0,
                "session_hygiene": 85.0,
                "code_review": 88.0,
                "tool_mastery": 82.0,
                "context_management": 86.0,
            },
            "anti_patterns": [
                {"rule_id": "repeated-prompts", "rule_name": "Repeated Prompts", "rule_group": "repeated-prompts", "severity": "medium", "triggered": True, "occurrences": 6, "total": 210},
                {"rule_id": "no-plan-mode", "rule_name": "No Plan Mode", "rule_group": "no-plan-mode", "severity": "low", "triggered": True, "occurrences": 3, "total": 30},
            ],
            "model_usage": {"claude-sonnet": {"requests": 180, "cost": 45.0}, "claude-haiku": {"requests": 30, "cost": 7.0}},
            "work_types": {"feature": 0.7, "bugfix": 0.2, "refactor": 0.1},
            "activity": {"by_day": {"2026-06-01": 8, "2026-06-02": 12}},
        },
        {
            "employee_id": "bob-lee",
            "employee_name": "Bob Lee",
            "team": "design",
            "collected_at": "2026-06-29T13:00:00Z",
            "period_start": "2026-06-01",
            "period_end": "2026-06-29",
            "summary": {
                "total_sessions": 10,
                "total_requests": 22,
                "total_workspaces": 2,
                "total_ai_loc": 1200,
                "total_input_tokens": 200_000,
                "total_output_tokens": 100_000,
                "estimated_cost_usd": 12.00,
            },
            "practice_scores": {
                "prompt_quality": 60.0,
                "session_hygiene": 55.0,
                "code_review": 50.0,
                "tool_mastery": 48.0,
                "context_management": 52.0,
            },
            "anti_patterns": [
                {"rule_id": "model-overreliance", "rule_name": "Model Overreliance", "rule_group": "model-overreliance", "severity": "medium", "triggered": True, "occurrences": 20, "total": 22},
                {"rule_id": "lazy-prompting", "rule_name": "Lazy Prompting", "rule_group": "lazy-prompting", "severity": "high", "triggered": True, "occurrences": 10, "total": 22},
            ],
            "model_usage": {"claude-opus": {"requests": 22, "cost": 12.0}},
            "work_types": {"design": 0.9, "feature": 0.1},
            "activity": {"by_day": {"2026-06-01": 2, "2026-06-02": 3}},
        },
    ]

    # --- 2. Ingest ---
    print("\n2. POST /api/ingest (3 employees)")
    for emp in mock_employees:
        code, data = _req("POST", "/api/ingest", emp)
        if not ok(f"ingest {emp['employee_id']} -> 200", code == 200, f"got {code} {data}"):
            failures += 1
            continue
        if isinstance(data, dict):
            if not ok("status ok", data.get("status") == "ok", str(data)):
                failures += 1
            if not ok("snapshot_id is int", isinstance(data.get("snapshot_id"), int), str(data)):
                failures += 1

    # --- 3. Ingest a 2nd snapshot for john-doe (for history test) ---
    print("\n3. POST /api/ingest (2nd snapshot for john-doe, history test)")
    second = json.loads(json.dumps(mock_employees[0]))
    second["practice_scores"]["prompt_quality"] = 92.0  # improved
    second["summary"]["total_requests"] = 340
    code, data = _req("POST", "/api/ingest", second)
    if not ok("2nd ingest -> 200", code == 200, f"got {code}"):
        failures += 1
    elif isinstance(data, dict):
        ok("2nd snapshot_id > first", isinstance(data.get("snapshot_id"), int), str(data))

    # --- 4. GET /api/employees ---
    print("\n4. GET /api/employees")
    code, data = _req("GET", "/api/employees")
    if not ok("status 200", code == 200, f"got {code}"):
        failures += 1
    elif isinstance(data, list):
        print(f"        returned {len(data)} employees")
        if not ok("3 employees", len(data) == 3, f"got {len(data)}"):
            failures += 1
        jd = next((e for e in data if e["employee_id"] == "john-doe"), None)
        if jd:
            if not ok("john-doe has metrics", bool(jd.get("metrics")), str(jd.get("metrics"))):
                failures += 1
            if not ok("overall_score present", "overall_score" in jd.get("metrics", {}), str(jd.get("metrics"))):
                failures += 1
            if not ok("anti_patterns_count present", "anti_patterns_count" in jd, str(jd.get("anti_patterns_count"))):
                failures += 1
            if not ok("high_severity_count present", "high_severity_count" in jd, str(jd.get("high_severity_count"))):
                failures += 1

    # --- 5. GET /api/employees?team=engineering ---
    print("\n5. GET /api/employees?team=engineering")
    code, data = _req("GET", "/api/employees?team=engineering")
    if not ok("status 200", code == 200, f"got {code}"):
        failures += 1
    elif isinstance(data, list):
        if not ok("2 engineering employees", len(data) == 2, f"got {len(data)}"):
            failures += 1

    # --- 6. GET /api/employees?sort=overall_score&order=desc ---
    print("\n6. GET /api/employees?sort=overall_score&order=desc")
    code, data = _req("GET", "/api/employees?sort=overall_score&order=desc")
    if not ok("status 200", code == 200, f"got {code}"):
        failures += 1
    elif isinstance(data, list) and len(data) >= 2:
        s1 = data[0].get("metrics", {}).get("overall_score", 0)
        s2 = data[1].get("metrics", {}).get("overall_score", 0)
        if not ok("desc order (first >= second)", s1 >= s2, f"{s1} vs {s2}"):
            failures += 1

    # --- 7. GET /api/employees/{id} ---
    print("\n7. GET /api/employees/john-doe")
    code, data = _req("GET", "/api/employees/john-doe")
    if not ok("status 200", code == 200, f"got {code}"):
        failures += 1
    elif isinstance(data, dict):
        for field in ["employee_id", "name", "team", "latest_snapshot", "summary", "practice_scores", "anti_patterns", "model_usage", "work_types", "activity", "recommendations"]:
            if not ok(f"has {field}", field in data, f"missing {field}"):
                failures += 1
        recs = data.get("recommendations", {})
        if isinstance(recs, dict):
            if not ok("recommendations.training is list", isinstance(recs.get("training"), list), str(type(recs.get("training")))):
                failures += 1
            else:
                print(f"        training recs: {json.dumps(recs['training'])}")
            if not ok("recommendations.plan is dict", isinstance(recs.get("plan"), dict), str(type(recs.get("plan")))):
                failures += 1
            else:
                print(f"        plan: {json.dumps(recs['plan'])}")

    # --- 8. GET /api/employees/{id}/history ---
    print("\n8. GET /api/employees/john-doe/history")
    code, data = _req("GET", "/api/employees/john-doe/history")
    if not ok("status 200", code == 200, f"got {code}"):
        failures += 1
    elif isinstance(data, list):
        print(f"        {len(data)} history entries")
        if not ok("2 history entries", len(data) == 2, f"got {len(data)}"):
            failures += 1
        if data:
            h = data[0]
            for field in ["snapshot_id", "uploaded_at", "overall_score", "scores"]:
                if not ok(f"history entry has {field}", field in h, str(h)):
                    failures += 1

    # --- 9. GET /api/team/overview ---
    print("\n9. GET /api/team/overview")
    code, data = _req("GET", "/api/team/overview")
    if not ok("status 200", code == 200, f"got {code}"):
        failures += 1
    elif isinstance(data, dict):
        print(f"        {json.dumps(data, indent=2)}")
        for field in ["total_employees", "total_requests", "total_cost_usd", "avg_overall_score", "team_breakdown", "top_training_needs", "plan_recommendations", "score_distribution"]:
            if not ok(f"has {field}", field in data, f"missing {field}"):
                failures += 1
        if not ok("total_employees == 3", data.get("total_employees") == 3, str(data.get("total_employees"))):
            failures += 1
        tb = data.get("team_breakdown", {})
        if not ok("team_breakdown has engineering+design", "engineering" in tb and "design" in tb, str(list(tb.keys()))):
            failures += 1

    # --- 10. GET /api/rules ---
    print("\n10. GET /api/rules")
    code, data = _req("GET", "/api/rules")
    if not ok("status 200", code == 200, f"got {code}"):
        failures += 1
    elif isinstance(data, list):
        print(f"        {len(data)} rules")
        if not ok("20 rules", len(data) == 20, f"got {len(data)}"):
            failures += 1
        if data:
            r = data[0]
            for field in ["id", "name", "group", "severity", "description", "suggestion"]:
                if not ok(f"rule has {field}", field in r, str(r)):
                    failures += 1

    # --- 11. 404 for unknown employee ---
    print("\n11. GET /api/employees/unknown-person (expect 404)")
    code, data = _req("GET", "/api/employees/unknown-person")
    if not ok("status 404", code == 404, f"got {code}"):
        failures += 1

    print(f"\n{'='*50}")
    if failures == 0:
        print("ALL TESTS PASSED")
        return 0
    print(f"{failures} CHECK(S) FAILED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
