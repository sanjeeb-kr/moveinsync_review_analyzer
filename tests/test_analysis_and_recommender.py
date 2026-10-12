import pytest
import pandas as pd
from datetime import datetime, timezone, timedelta
from src.analysis import compute_basic_numbers
from src.recommender import compute_star_impact_scenario, analyze_problems, export_action_items_csv

def test_star_impact_scenario_calculation():
    """
    Tests mathematical correctness of Star Impact Scenario:
    Delta = sum(max(0, 4 - score_i)) / total_reviews
    """
    data = [
        {"review_id": "1", "score": 1, "issue": "tracking_and_eta"},  # deficit: 3
        {"review_id": "2", "score": 2, "issue": "tracking_and_eta"},  # deficit: 2
        {"review_id": "3", "score": 5, "issue": "tracking_and_eta"},  # deficit: 0
        {"review_id": "4", "score": 4, "issue": "login_and_otp"},      # not in issue
    ]
    df = pd.DataFrame(data)
    impact = compute_star_impact_scenario(df, "tracking_and_eta")
    
    # Total reviews = 4. Deficit = 3 + 2 = 5.
    # Expected delta = 5 / 4 = 1.25. Current avg = (1+2+5+4)/4 = 3.0. New avg = 4.25.
    assert impact["delta"] == 1.25
    assert impact["current_avg"] == 3.0
    assert impact["new_avg"] == 4.25
    assert impact["affected_count"] == 2

def test_basic_numbers_and_thresholds():
    """Tests basic statistics, gap calculation, and minimum trend sample thresholds."""
    now = datetime.now(timezone.utc)
    data = []
    # 20 reviews for latest 30 days
    for i in range(20):
        data.append({
            "review_id": f"r_new_{i}",
            "score": 4,
            "at": (now - timedelta(days=5)).isoformat(),
            "at_dt": now - timedelta(days=5),
            "app_version": "12.19.0",
            "reply_content": None,
            "reply_latency_hours": None
        })
    # 10 reviews for previous 30 days (< 15 threshold)
    for i in range(10):
        data.append({
            "review_id": f"r_old_{i}",
            "score": 2,
            "at": (now - timedelta(days=45)).isoformat(),
            "at_dt": now - timedelta(days=45),
            "app_version": "12.18.0",
            "reply_content": None,
            "reply_latency_hours": None
        })
    df = pd.DataFrame(data)
    meta = {"score": 4.5, "ratings_count": 50000}
    
    res = compute_basic_numbers(df, meta)
    assert res["summary"]["total_reviews"] == 30
    assert "Insufficient sample size" in res["period_comparison"]["trend_verbal"]

def test_denominators_and_shares():
    """
    Tests that:
    1. share_of_all_reviews uses total_reviews as denominator
    2. share_of_low_star uses total_low_star as denominator
    3. rating_gap = avg_text_rating - listing_score
    """
    data = [
        {"review_id": "r1", "score": 1, "issue": "login_and_otp", "is_classified": 1, "at": "2026-10-01T00:00:00Z"},
        {"review_id": "r2", "score": 2, "issue": "login_and_otp", "is_classified": 1, "at": "2026-10-01T00:00:00Z"},
        {"review_id": "r3", "score": 5, "issue": "login_and_otp", "is_classified": 1, "at": "2026-10-01T00:00:00Z"},
        {"review_id": "r4", "score": 1, "issue": "tracking_and_eta", "is_classified": 1, "at": "2026-10-01T00:00:00Z"},
        {"review_id": "r5", "score": 5, "issue": "positive_feedback", "is_classified": 1, "at": "2026-10-01T00:00:00Z"},
    ]
    df = pd.DataFrame(data)
    df["at_dt"] = pd.to_datetime(df["at"])
    meta = {"score": 4.6, "ratings_count": 100000}

    # Total = 5, Total Low = 3 (scores 1, 2, 1)
    # login_and_otp has 3 total reviews, 2 low-star reviews
    res = analyze_problems(df)
    login_prob = next(p for p in res["ranked_problems"] if p["issue_key"] == "login_and_otp")

    # share_of_all = 3 / 5 * 100 = 60.0%
    assert login_prob["share_of_all_reviews"] == 60.0
    # share_of_low = 2 / 3 * 100 = 66.67%
    assert login_prob["share_of_low_star"] == 66.67

    num_res = compute_basic_numbers(df, meta)
    # avg text = (1+2+5+1+5)/5 = 2.8. gap = 2.8 - 4.6 = -1.8
    assert num_res["summary"]["listing_score"] == 4.6
    assert num_res["summary"]["avg_text_rating"] == 2.8
    assert num_res["summary"]["rating_gap"] == -1.8

def test_trend_small_sample_inconclusive():
    """
    Tests that small samples (< 5 in either period) prevent misleading percentage trends
    and are marked inconclusive.
    """
    now = datetime.now(timezone.utc)
    # Only 2 reviews in recent period, 0 in prev period
    data = [
        {"review_id": "r1", "score": 1, "issue": "login_and_otp", "is_classified": 1, "at": (now - timedelta(days=2)).isoformat()},
        {"review_id": "r2", "score": 1, "issue": "login_and_otp", "is_classified": 1, "at": (now - timedelta(days=5)).isoformat()},
    ]
    df = pd.DataFrame(data)
    df["at_dt"] = pd.to_datetime(df["at"])
    res = analyze_problems(df)
    login_prob = next(p for p in res["ranked_problems"] if p["issue_key"] == "login_and_otp")

    assert login_prob["is_trend_conclusive"] is False
    assert login_prob["trend_change_pct"] is None
    assert "Inconclusive" in login_prob["trend_display"]

def test_safety_escalation_rule():
    """
    Tests that only safety_complaints issue gets is_safety = True and the safety boost,
    while technical categories (login_and_otp) do NOT get marked as safety escalation.
    """
    now = datetime.now(timezone.utc)
    data = [
        {"review_id": "r1", "score": 1, "issue": "login_and_otp", "is_classified": 1, "at": now.isoformat(), "safety_flag": 0},
        {"review_id": "r2", "score": 1, "issue": "safety_complaints", "is_classified": 1, "at": now.isoformat(), "safety_flag": 1},
    ]
    df = pd.DataFrame(data)
    df["at_dt"] = pd.to_datetime(df["at"])
    res = analyze_problems(df)

    login_prob = next(p for p in res["ranked_problems"] if p["issue_key"] == "login_and_otp")
    safety_prob = next(p for p in res["ranked_problems"] if p["issue_key"] == "safety_complaints")

    assert login_prob["is_safety"] is False
    assert safety_prob["is_safety"] is True
    assert safety_prob["ranking_score"] >= 100.0

def test_action_items_csv_export(tmp_path):
    """Tests Jira/Linear CSV export structure."""
    out_csv = tmp_path / "action_items.csv"
    mock_specs = [{
        "issue_key": "login_and_otp",
        "title": "Login And Otp",
        "dominant_responsibility": "app_technical",
        "estimated_effort": "small",
        "owner": "Auth Lead",
        "hypothesis": "SMS timeout",
        "proposed_change": "Add WhatsApp OTP",
        "first_14_days": "Deploy SMS retriever",
        "acceptance_criteria": "Auto-read OTP",
        "what_to_measure": "Login success rate"
    }]
    path = export_action_items_csv(mock_specs, out_csv)
    df_out = pd.read_csv(path)
    assert len(df_out) == 1
    assert "Issue Key" in df_out.columns
    assert "Summary" in df_out.columns
    assert "Acceptance Criteria" in df_out.columns
    assert df_out.iloc[0]["Summary"] == "Fix Login And Otp (app_technical)"
