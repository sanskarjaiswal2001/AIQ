from rules_meta import all_rules


def test_audited_rules_disable_weak_proxies_by_default():
    rules = {r["id"]: r for r in all_rules()}

    for rule_id in ["late-night-coding", "weekend-overwork", "tunnel-vision", "no-plan-mode", "no-skills"]:
        assert rules[rule_id]["default_enabled"] is False
        assert rules[rule_id]["audit_status"] == "off"

    assert rules["speed-accept"]["audit_status"] == "keep"
    assert rules["context-engineering-gaps"]["default_enabled"] is True
    assert rules["context-engineering-gaps"]["basis"]
