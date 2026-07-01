from cost_engine import billing_months_for_period, interpret_cost


def test_rolling_seat_spend_uses_plan_price_times_calendar_months():
    summary = {
        "period_start": "2026-01-15",
        "period_end": "2026-04-02",
        "total_requests": 420,
        "estimated_cost_usd": 17.25,
    }
    plan = {
        "billing_mode": "seat_rolling",
        "seat_cost_usd": 25,
        "rolling_window_usd": 25,
        "rolling_window_days": 30,
    }

    info = interpret_cost(summary, plan)

    assert billing_months_for_period(summary) == 4
    assert info["display_cost"] == 100
    assert info["cost_label"] == "Billed Seat Spend"
    assert info["estimated_token_cost"] == 17.25
    assert info["utilization"] == 0.69
    assert info["remaining_budget"] == 7.75
    assert info["usage_label"] == "Rolling Window Pressure"


def test_api_plan_keeps_token_estimate_as_spend():
    info = interpret_cost(
        {"period_start": "2026-01-01", "period_end": "2026-04-30", "estimated_cost_usd": 17.25},
        {"billing_mode": "api"},
    )

    assert info["display_cost"] == 17.25
    assert info["cost_label"] == "Estimated API Spend"
    assert info["billed_months"] == 4
