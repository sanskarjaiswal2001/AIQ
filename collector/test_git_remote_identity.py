from aiq_collector.analyzer import Analyzer
from aiq_collector.models import Session, SessionRequest


def test_analyzer_uses_git_remote_as_project_identity_across_protocols(tmp_path):
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text('[remote "origin"]\n    url = git@github.com:acme/payments-api.git\n')

    session = Session(
        session_id="s1",
        workspace_name="payments-api",
        workspace_path=str(repo),
        harness="codex",
        requests=[SessionRequest(message="build feature", input_tokens=10, output_tokens=5)],
    )
    metrics = Analyzer().analyze([session], employee_id="dev-1")

    assert metrics["projects"][0]["project_id"] == "github.com/acme/payments-api"
    assert metrics["projects"][0]["normalized_git_remote"] == "github.com/acme/payments-api"
    assert metrics["projects"][0]["harness_usage"] == {"codex": 1}
