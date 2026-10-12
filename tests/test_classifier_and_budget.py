import pytest
import sqlite3
from datetime import datetime, timezone, timedelta
from src.db import init_db, get_connection
from src.budget import BudgetManager, QuotaExhaustedException, BudgetExceededException
from src.classifier import (
    validate_and_sanitize_label, try_rule_classification,
    mock_classify_review, ReviewClassifier
)
from config.config import ALLOWED_ISSUES, ALLOWED_RESPONSIBILITIES, ALLOWED_JOURNEY_STAGES

def test_taxonomy_validation():
    """Ensures arbitrary AI output is forced into allowed taxonomy values."""
    raw = {
        "issue": "totally_invented_issue",
        "responsibility": "unknown_actor",
        "journey_stage": "mars_flight",
        "severity": 10,
        "safety_flag": 1,
        "evidence_quote": "nonexistent text"
    }
    cleaned = validate_and_sanitize_label(raw, "Valid original review content here.")
    assert cleaned["issue"] in ALLOWED_ISSUES
    assert cleaned["responsibility"] in ALLOWED_RESPONSIBILITIES
    assert cleaned["journey_stage"] in ALLOWED_JOURNEY_STAGES
    assert cleaned["severity"] == 3  # safety flag forces severity 3
    assert cleaned["is_uncertain"] == 1  # quote was not in text

def test_verbatim_quote_validation():
    """Ensures exact matching quote is verified and recognized."""
    text = "Driver was driving very rashly on the highway."
    raw = {
        "issue": "driver_behaviour_or_communication",
        "responsibility": "operations_fleet",
        "journey_stage": "in-ride",
        "severity": 2,
        "safety_flag": 0,
        "evidence_quote": "driving very rashly"
    }
    cleaned = validate_and_sanitize_label(raw, text)
    assert cleaned["evidence_quote"] == "driving very rashly"
    assert cleaned["is_uncertain"] == 0

def test_rule_prefilter():
    """Ensures short positive reviews are labeled locally with zero API cost."""
    match1 = try_rule_classification("Very good app and smooth cab service", 5)
    assert match1 is not None
    assert match1["issue"] == "positive_feedback"
    assert match1["classification_source"] == "rule"

    # Negative keyword prevents positive rule match
    match_neg = try_rule_classification("Good app but cab is very late", 4)
    assert match_neg is None

    # Low score prevents positive rule match
    match_low = try_rule_classification("good", 2)
    assert match_low is None

def test_budget_daily_limit(tmp_path):
    """Ensures daily limit stops pipeline before exceeding allowed requests."""
    test_db = tmp_path / "budget_test.db"
    init_db(test_db)
    bm = BudgetManager(db_path=test_db, max_per_day=2, delay_sec=0)

    # First request
    bm.check_permission()
    bm.record_request_success(10)
    assert bm.get_status()["requests_remaining"] == 1

    # Second request
    bm.check_permission()
    bm.record_request_success(10)
    assert bm.get_status()["requests_remaining"] == 0

    # Third request must raise BudgetExceededException
    with pytest.raises(BudgetExceededException):
        bm.check_permission()

def test_quota_exhaustion_immediate_stop(tmp_path):
    """
    CRITICAL REQUIREMENT:
    On quota exhaustion (429), job stops immediately, error is recorded in SQLite,
    cooldown timestamp is set, and no subsequent requests can proceed.
    """
    test_db = tmp_path / "quota_test.db"
    init_db(test_db)
    bm = BudgetManager(db_path=test_db, max_per_day=16, delay_sec=0)

    # Simulate 429 Quota Exhaustion
    bm.record_quota_exhausted("Resource exhausted: 429 daily limit reached", retry_after_seconds=3600)
    
    status = bm.get_status()
    assert status["quota_exhausted"] is True
    assert status["can_proceed"] is False
    assert "429" in status["last_error"]

    # Immediate call should raise QuotaExhaustedException
    with pytest.raises(QuotaExhaustedException):
        bm.check_permission()

def test_resume_after_interruption_no_reprocessing(tmp_path):
    """Ensures already-classified reviews are never reprocessed when pipeline resumes."""
    test_db = tmp_path / "resume_test.db"
    init_db(test_db)
    conn = get_connection(test_db)
    cur = conn.cursor()

    # Insert 3 reviews, 1 already classified
    now_iso = datetime.now(timezone.utc).isoformat()
    cur.execute("""
        INSERT INTO reviews (review_id, score, content, at, is_classified, issue)
        VALUES ('r1', 1, 'Late cab', ?, 1, 'late_pickup_or_vehicle_assignment')
    """, (now_iso,))
    cur.execute("""
        INSERT INTO reviews (review_id, score, content, at, is_classified)
        VALUES ('r2', 1, 'App crashed', ?, 0)
    """, (now_iso,))
    cur.execute("""
        INSERT INTO reviews (review_id, score, content, at, is_classified)
        VALUES ('r3', 5, 'Super service', ?, 0)
    """, (now_iso,))
    conn.commit()
    conn.close()

    classifier = ReviewClassifier(db_path=test_db, use_mock=True)
    res = classifier.run_classification_pipeline()

    conn = get_connection(test_db)
    cur = conn.cursor()
    # Check that r1 kept its original label
    r1_label = cur.execute("SELECT issue FROM reviews WHERE review_id = 'r1'").fetchone()[0]
    assert r1_label == "late_pickup_or_vehicle_assignment"
    
    # All are now classified
    pending = cur.execute("SELECT COUNT(*) FROM reviews WHERE is_classified = 0").fetchone()[0]
    assert pending == 0
    conn.close()
