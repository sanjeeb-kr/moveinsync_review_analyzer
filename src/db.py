import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import sqlite3
import json
from datetime import datetime
from config.config import DB_PATH


def get_connection(db_path=None):
    if db_path is None:
        db_path = DB_PATH
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path=None):
    conn = get_connection(db_path)
    cur = conn.cursor()

    # Listing Metrics Table (separate from individual reviews)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS listing_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT NOT NULL,
        app_id TEXT NOT NULL,
        title TEXT,
        score REAL,
        ratings_count INTEGER,
        histogram TEXT,
        star_1 INTEGER,
        star_2 INTEGER,
        star_3 INTEGER,
        star_4 INTEGER,
        star_5 INTEGER,
        country TEXT DEFAULT 'in',
        source TEXT DEFAULT 'Google Play Store (India)',
        retrieval_method TEXT DEFAULT 'google-play-scraper'
    )
    """)

    # Ensure schema migrations for existing database
    existing_cols = [c[1] for c in cur.execute("PRAGMA table_info(listing_metrics)").fetchall()]
    if "country" not in existing_cols:
        cur.execute("ALTER TABLE listing_metrics ADD COLUMN country TEXT DEFAULT 'in'")
    if "source" not in existing_cols:
        cur.execute("ALTER TABLE listing_metrics ADD COLUMN source TEXT DEFAULT 'Google Play Store (India)'")
    if "retrieval_method" not in existing_cols:
        cur.execute("ALTER TABLE listing_metrics ADD COLUMN retrieval_method TEXT DEFAULT 'google-play-scraper'")
    conn.commit()

    # Reviews Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        review_id TEXT PRIMARY KEY,
        score INTEGER NOT NULL,
        content TEXT NOT NULL,
        review_created_version TEXT,
        app_version TEXT,
        at TEXT NOT NULL,
        thumbs_up_count INTEGER DEFAULT 0,
        reply_content TEXT,
        replied_at TEXT,
        detected_language TEXT,
        rating_bucket TEXT,
        is_classified INTEGER DEFAULT 0,
        classified_at TEXT,
        classification_source TEXT DEFAULT 'pending',
        issue TEXT,
        extra_issues TEXT,
        responsibility TEXT,
        journey_stage TEXT,
        severity INTEGER,
        safety_flag INTEGER DEFAULT 0,
        confidence REAL,
        evidence_quote TEXT,
        is_uncertain INTEGER DEFAULT 0
    )
    """)

    # Budget & Rate Limits Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS api_budget (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,
        request_count INTEGER DEFAULT 0,
        reviews_classified INTEGER DEFAULT 0,
        last_request_at TEXT,
        quota_exhausted INTEGER DEFAULT 0,
        cooldown_until TEXT,
        last_error TEXT
    )
    """)

    # Action Items Table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS action_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        issue_key TEXT NOT NULL,
        priority TEXT DEFAULT 'P1',
        status TEXT DEFAULT 'proposed',
        owner TEXT,
        effort TEXT,
        description TEXT,
        acceptance_criteria TEXT,
        telemetry TEXT,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print("Database initialized successfully at", DB_PATH)
