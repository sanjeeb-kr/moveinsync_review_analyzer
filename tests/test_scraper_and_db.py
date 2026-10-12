import pytest
import sqlite3
import pandas as pd
from datetime import datetime, timezone, timedelta
from src.db import init_db, get_connection
from src.scraper import compute_rating_bucket, detect_language, import_reviews_from_csv

def test_rating_buckets():
    """Validates low, medium, and high rating bucket calculations."""
    assert compute_rating_bucket(1) == "Low"
    assert compute_rating_bucket(2) == "Low"
    assert compute_rating_bucket(3) == "Medium"
    assert compute_rating_bucket(4) == "High"
    assert compute_rating_bucket(5) == "High"

def test_language_detection():
    """Validates language detection for English, Hinglish, and Indic scripts."""
    # Pure English (including reviews that previously had false-positive Hinglish triggers)
    assert detect_language("This application is working properly.") == "English"
    assert detect_language("Login is not working properly, no otp received.") == "English"
    assert detect_language("Worst cab service ever experienced, driver was late.") == "English"
    
    # Romanized Hindi (Hinglish)
    assert detect_language("bhot bekar app hai cab time pe nahi aati") == "Hinglish"
    assert detect_language("kripya cab time se bhejo bhai") == "Hinglish"
    
    # Devanagari Hindi and Marathi
    assert detect_language("बहुत ही खराब सेवा है") == "Hindi (Devanagari)"
    assert detect_language("गाडी वेळेवर येत नाही") == "Marathi"

def test_db_init_and_incremental_insert(tmp_path):
    """Tests SQLite table creation, deduplication by review ID, and incremental persistence."""
    test_db = tmp_path / "test.db"
    init_db(test_db)

    conn = get_connection(test_db)
    cur = conn.cursor()

    # Synthetic review fixtures
    rev1 = {
        "review_id": "rev-synthetic-001",
        "score": 1,
        "content": "Cab never arrived on time for my morning shift.",
        "review_created_version": "12.19.0",
        "app_version": "12.19.0",
        "at": datetime.now(timezone.utc).isoformat(),
        "thumbs_up_count": 2,
        "reply_content": None,
        "replied_at": None,
        "detected_language": "English",
        "rating_bucket": "Low"
    }

    cur.execute("""
        INSERT OR IGNORE INTO reviews (
            review_id, score, content, review_created_version, app_version,
            at, thumbs_up_count, reply_content, replied_at, detected_language,
            rating_bucket
        ) VALUES (
            :review_id, :score, :content, :review_created_version, :app_version,
            :at, :thumbs_up_count, :reply_content, :replied_at, :detected_language,
            :rating_bucket
        )
    """, rev1)
    conn.commit()

    count1 = cur.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    assert count1 == 1

    # Attempt to insert identical review_id (simulate duplicate)
    cur.execute("""
        INSERT OR IGNORE INTO reviews (
            review_id, score, content, review_created_version, app_version,
            at, thumbs_up_count, reply_content, replied_at, detected_language,
            rating_bucket
        ) VALUES (
            :review_id, :score, :content, :review_created_version, :app_version,
            :at, :thumbs_up_count, :reply_content, :replied_at, :detected_language,
            :rating_bucket
        )
    """, rev1)
    conn.commit()

    count2 = cur.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    assert count2 == 1, "Duplicate review ID must not create a duplicate row."
    conn.close()

def test_csv_import_fallback(tmp_path):
    """Tests CSV fallback import when scraping is bypassed."""
    test_db = tmp_path / "test_csv.db"
    csv_file = tmp_path / "synthetic_import.csv"
    
    df_synth = pd.DataFrame([
        {"review_id": "csv-01", "score": 2, "content": "Booking rejected", "at": "2026-09-01T10:00:00"},
        {"review_id": "csv-02", "score": 5, "content": "Super app", "at": "2026-09-02T10:00:00"}
    ])
    df_synth.to_csv(csv_file, index=False)

    inserted = import_reviews_from_csv(str(csv_file), db_path=test_db)
    assert inserted >= 0
    
    conn = get_connection(test_db)
    count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()
    assert count == 2
