import importlib


def _load_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "aiq-test.db"))
    import database
    database = importlib.reload(database)
    database.init_db()
    return database


def test_admin_project_matches_https_and_ssh_git_remotes_with_harness_rollup(tmp_path, monkeypatch):
    db = _load_db(tmp_path, monkeypatch)
    db.create_project(
        "",
        "Payments API",
        customer_name="Blue Finch Retail",
        git_remote_url="https://github.com/acme/payments-api.git",
    )

    payload = {
        "employee_id": "dev-1",
        "employee_name": "Dev One",
        "team": "engineering",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "summary": {"total_sessions": 2, "total_requests": 17, "estimated_cost_usd": 3.5},
        "practice_scores": {},
        "anti_patterns": [],
        "projects": [{
            "project_id": "github.com/acme/payments-api",
            "project_name": "payments-api",
            "project_path": "/work/payments-api",
            "git_remote_url": "git@github.com:acme/payments-api.git",
            "normalized_git_remote": "github.com/acme/payments-api",
            "harness_usage": {"claude": 1, "codex": 1},
            "sessions": 2,
            "requests": 17,
            "estimated_cost_usd": 3.5,
        }],
    }
    db.ingest_snapshot(payload)

    projects = {p["project_id"]: p for p in db.get_all_projects()}
    assert "github.com/acme/payments-api" in projects
    assert projects["github.com/acme/payments-api"]["total_requests"] == 17
    assert projects["github.com/acme/payments-api"]["customer_name"] == "Blue Finch Retail"
    assert projects["github.com/acme/payments-api"]["harness_usage"] == {"claude": 1, "codex": 1}


def test_unknown_git_remote_stays_other_untracked(tmp_path, monkeypatch):
    db = _load_db(tmp_path, monkeypatch)
    db.create_project("known", "Known", git_remote_url="https://github.com/acme/known.git")
    db.ingest_snapshot({
        "employee_id": "dev-2",
        "employee_name": "Dev Two",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "summary": {"total_sessions": 1, "total_requests": 4, "estimated_cost_usd": 1.0},
        "practice_scores": {},
        "anti_patterns": [],
        "projects": [{"project_id": "unknown", "project_name": "unknown", "normalized_git_remote": "github.com/acme/other", "requests": 4}],
    })
    projects = {p["project_id"]: p for p in db.get_all_projects()}
    assert projects["other"]["total_requests"] == 4
    assert projects["github.com/acme/known"]["total_requests"] == 0
