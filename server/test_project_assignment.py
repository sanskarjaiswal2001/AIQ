import importlib


def _load_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "aiq-test.db"))
    import database
    database = importlib.reload(database)
    database.init_db()
    return database


def test_detected_usage_defaults_to_other_until_employee_assigns_project(tmp_path, monkeypatch):
    db = _load_db(tmp_path, monkeypatch)
    payload = {
        "employee_id": "dev-1",
        "employee_name": "Dev One",
        "team": "engineering",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "summary": {"total_sessions": 1, "total_requests": 10, "estimated_cost_usd": 2.0},
        "practice_scores": {},
        "anti_patterns": [],
        "projects": [{"project_id": "home-folder", "project_name": "home", "project_path": "/Users/dev", "requests": 10, "estimated_cost_usd": 2.0}],
    }
    db.ingest_snapshot(payload)

    assert db.get_all_projects()[0]["project_id"] == "other"

    db.create_project("client-app", "Client App")
    db.set_project_assignment("dev-1", "home-folder", "client-app")

    projects = {p["project_id"]: p for p in db.get_all_projects()}
    assert projects["client-app"]["total_requests"] == 10
    assert projects["client-app"]["employees"][0]["detected_project_id"] == "home-folder"
