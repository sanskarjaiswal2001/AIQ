import importlib


def _load_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "aiq-test.db"))
    import database
    database = importlib.reload(database)
    database.init_db()
    return database


def test_admin_overview_uses_plan_billed_spend_not_token_estimate(tmp_path, monkeypatch):
    db = _load_db(tmp_path, monkeypatch)
    payload = {
        "employee_id": "office-user",
        "employee_name": "Office User",
        "team": "engineering",
        "period_start": "2026-01-15",
        "period_end": "2026-04-02",
        "summary": {
            "total_sessions": 12,
            "total_requests": 120,
            "total_workspaces": 1,
            "total_ai_loc": 2000,
            "total_input_tokens": 100000,
            "total_output_tokens": 50000,
            "estimated_cost_usd": 17.25,
        },
        "practice_scores": {
            "prompt_quality": 90,
            "session_hygiene": 90,
            "code_review": 90,
            "tool_mastery": 90,
            "context_management": 90,
        },
        "anti_patterns": [],
        "projects": [
            {
                "project_id": "finance-app",
                "project_name": "finance-app",
                "project_path": "/Users/office/Work/finance-app",
                "sessions": 12,
                "requests": 120,
                "ai_loc": 2000,
                "user_loc": 250,
                "input_tokens": 100000,
                "output_tokens": 50000,
                "estimated_cost_usd": 17.25,
                "first_activity": "2026-01-15",
                "last_activity": "2026-04-02",
                "active_days": 28,
                "model_usage": {"claude-sonnet": {"requests": 120}},
                "work_types": {"feature": 12},
                "git_branches": ["main"],
                "files_edited_count": 8,
            }
        ],
    }

    db.ingest_snapshot(payload)
    db.set_plan_override(
        "office-user",
        {
            "provider": "claude",
            "plan_id": "custom_rolling_window",
            "plan_name": "Office Claude Team Seat",
            "billing_mode": "seat_rolling",
            "seat_cost_usd": 25,
            "rolling_window_usd": 25,
            "rolling_window_days": 30,
        },
    )

    overview = db.get_team_overview()
    assert overview["total_cost_usd"] == 100
    assert overview["estimated_token_cost_usd"] == 17.25
    assert overview["team_breakdown"]["engineering"]["total_cost"] == 100

    employees = db.list_employees()
    assert employees[0]["metrics"]["display_cost_usd"] == 100
    assert employees[0]["metrics"]["estimated_token_cost_usd"] == 17.25

    projects = db.get_all_projects()
    assert projects[0]["total_cost_usd"] == 100
    assert projects[0]["estimated_token_cost_usd"] == 17.25
    assert projects[0]["employees"][0]["cost_usd"] == 100
