import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import re
import json
import time
import logging
from datetime import datetime, timezone, timedelta

from google_play_scraper import app as play_app, reviews as play_reviews, Sort
from config.config import (
    APP_ID, LOCALES, DEFAULT_COUNTRY, DAYS_HISTORY,
    RAW_DATA_PATH, DB_PATH
)
from src.db import get_connection, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("scraper")

DISTINCT_HINGLISH_KEYWORDS = {
    "hai", "hain", "nahi", "nhi", "raha", "rahi", "rahe", "bekar", "bhot", "bahut",
    "aati", "aata", "aate", "karo", "karna", "krte", "kare", "karein", "aur", "yeh",
    "iss", "iski", "iska", "iske", "kya", "koi", "abhi", "accha", "achha", "achhi",
    "gaadi", "gadi", "chalata", "chala", "bura", "buri", "kaam", "hoga", "hogi",
    "hoge", "kuch", "kuchh", "paise", "bakwas", "faltu", "ganda", "gandi", "dikkat",
    "pareshan", "pareshani", "samashya", "kripya", "dhanyawad", "shukriya", "mat",
    "waqt", "kabtak", "chalana", "bol", "bola", "boli", "karte", "hum", "tum",
    "mera", "meri", "mere", "tera", "teri", "tere", "unka", "unki", "unke", "sirf",
    "lekin", "magar", "kyunki", "chahiye", "chalao", "dhoka", "chor", "dhokhadhadi",
    "bhai", "bhejo", "bhejna", "bhejiye", "jaldi", "theek", "thik", "sahi", "galat", "pehle", "baad"
}

COMMON_ENGLISH_WORDS = {
    "the", "and", "of", "to", "in", "that", "it", "is", "was", "for", "on", "are",
    "with", "as", "at", "be", "this", "have", "from", "or", "one", "had", "by",
    "word", "but", "not", "what", "all", "were", "we", "when", "your", "can",
    "said", "there", "use", "an", "each", "which", "she", "do", "how", "their",
    "if", "will", "up", "other", "about", "out", "many", "then", "them", "these",
    "so", "some", "her", "would", "make", "like", "him", "into", "time", "has",
    "look", "two", "more", "write", "go", "see", "number", "no", "way", "could",
    "people", "my", "than", "first", "been", "call", "who", "its", "now", "find",
    "down", "day", "did", "get", "come", "made", "may", "part", "app", "application",
    "cab", "driver", "service", "cabs", "ride", "rides", "office", "home", "good",
    "bad", "update", "worst", "rating", "trip", "work", "hours", "late", "delay",
    "please", "very", "nice", "smooth", "experience", "login", "booking", "schedule"
}

def detect_language(text: str) -> str:
    """
    Detects language or script mix from review text:
    - Indic scripts: Hindi (Devanagari), Tamil, Telugu, Kannada, Malayalam, Bengali, Gujarati, Punjabi, Marathi
    - Latin script: English vs Romanized Hindi (Hinglish)
    """
    if not text or not text.strip():
        return "Unknown"

    text_clean = text.strip()
    
    # Check Indian script blocks
    if re.search(r"[\u0900-\u097F]", text_clean):
        # Devanagari script (Hindi / Marathi)
        if any(w in text_clean for w in ["आहे", "नाही", "झाले", "करू", "गाडी"]):
            return "Marathi"
        return "Hindi (Devanagari)"
    if re.search(r"[\u0B80-\u0BFF]", text_clean):
        return "Tamil"
    if re.search(r"[\u0C00-\u0C7F]", text_clean):
        return "Telugu"
    if re.search(r"[\u0C80-\u0CFF]", text_clean):
        return "Kannada"
    if re.search(r"[\u0D00-\u0D7F]", text_clean):
        return "Malayalam"
    if re.search(r"[\u0980-\u09FF]", text_clean):
        return "Bengali"
    if re.search(r"[\u0A80-\u0AFF]", text_clean):
        return "Gujarati"
    if re.search(r"[\u0A00-\u0A7F]", text_clean):
        return "Punjabi"

    # Latin text analysis: English vs Romanized Hindi (Hinglish)
    words = re.findall(r"\b[a-zA-Z]+\b", text_clean.lower())
    if not words:
        return "Other"

    hinglish_cnt = sum(1 for w in words if w in DISTINCT_HINGLISH_KEYWORDS)
    english_cnt = sum(1 for w in words if w in COMMON_ENGLISH_WORDS)

    # If distinct Hindi words exist and dominate or no English stopwords present
    if (hinglish_cnt >= 2 and hinglish_cnt >= english_cnt) or (hinglish_cnt >= 1 and english_cnt == 0):
        return "Hinglish"
    
    return "English"


def compute_rating_bucket(score: int) -> str:
    """Rating bucket computed in Python: Low = 1–2, Medium = 3, High = 4–5."""
    if score in (1, 2):
        return "Low"
    elif score == 3:
        return "Medium"
    else:
        return "High"

def fetch_listing_metrics(app_id: str = APP_ID, country: str = DEFAULT_COUNTRY) -> dict:
    """
    Fetches official Play Store listing metadata for the specified country:
    Title, current score, total ratings count, and star histogram.
    Google Play calculates regional ratings (e.g. India country='in' vs US country='us').
    """
    logger.info(f"Fetching official Play Store listing details for '{app_id}' (country={country})...")
    app_details = play_app(app_id, lang="en", country=country)
    histogram = app_details.get("histogram", [0, 0, 0, 0, 0])

    
    # histogram from google-play-scraper is list [star_1, star_2, star_3, star_4, star_5]
    metrics = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "app_id": app_id,
        "title": app_details.get("title", ""),
        "score": float(app_details.get("score") or 0.0),
        "ratings_count": int(app_details.get("ratings") or 0),
        "histogram": json.dumps(histogram),
        "star_1": histogram[0] if len(histogram) > 0 else 0,
        "star_2": histogram[1] if len(histogram) > 1 else 0,
        "star_3": histogram[2] if len(histogram) > 2 else 0,
        "star_4": histogram[3] if len(histogram) > 3 else 0,
        "star_5": histogram[4] if len(histogram) > 4 else 0,
        "country": country,
        "source": "Google Play Store (India)",
        "retrieval_method": f"google-play-scraper (lang=en, country={country})"
    }
    return metrics

def save_listing_metrics(metrics: dict, db_path=None):
    """Saves official listing metrics to SQLite database."""
    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO listing_metrics (
            timestamp, app_id, title, score, ratings_count,
            histogram, star_1, star_2, star_3, star_4, star_5,
            country, source, retrieval_method
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        metrics["timestamp"], metrics["app_id"], metrics["title"],
        metrics["score"], metrics["ratings_count"], metrics["histogram"],
        metrics["star_1"], metrics["star_2"], metrics["star_3"],
        metrics["star_4"], metrics["star_5"],
        metrics.get("country", "in"),
        metrics.get("source", "Google Play Store (India)"),
        metrics.get("retrieval_method", "google-play-scraper (country=in)")
    ))
    conn.commit()
    conn.close()
    logger.info(f"Saved listing metrics: Score={metrics['score']}, Total Ratings={metrics['ratings_count']}")

def collect_reviews(
    app_id: str = APP_ID,
    days_history: int = DAYS_HISTORY,
    locales: list = LOCALES,
    db_path=None
) -> tuple[int, int]:
    """
    Collects reviews from Play Store across multiple locales for the last N days.
    Deduplicates by review ID, strips reviewer names, saves raw copy, and persists incrementally to SQLite.
    Returns (new_reviews_count, total_reviews_in_db).
    """
    init_db(db_path)
    
    # 1. Fetch & save live listing metrics
    listing_meta = fetch_listing_metrics(app_id)
    save_listing_metrics(listing_meta, db_path)

    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_history)
    logger.info(f"Collecting reviews since {cutoff_date.strftime('%Y-%m-%d')} ({days_history} days)...")

    # Load existing review IDs from database to optimize incremental checks
    conn = get_connection(db_path)
    cur = conn.cursor()
    existing_ids = set(row[0] for row in cur.execute("SELECT review_id FROM reviews").fetchall())
    conn.close()
    logger.info(f"Database currently holds {len(existing_ids)} existing reviews.")

    all_scraped_reviews = {}
    new_reviews = []

    for lang in locales:
        logger.info(f"Scraping locale '{lang}' (country={DEFAULT_COUNTRY})...")
        token = None
        has_more = True
        consecutive_old = 0
        batch_num = 0

        while has_more:
            batch_num += 1
            try:
                batch, token = play_reviews(
                    app_id,
                    lang=lang,
                    country=DEFAULT_COUNTRY,
                    sort=Sort.NEWEST,
                    count=100,
                    continuation_token=token
                )
            except Exception as e:
                logger.warning(f"Error fetching reviews for lang={lang}: {e}")
                break

            if not batch:
                break

            stop_locale = False
            for r in batch:
                rev_id = r.get("reviewId")
                rev_date = r.get("at")
                if rev_date:
                    # Ensure datetime is timezone-aware
                    if rev_date.tzinfo is None:
                        rev_date = rev_date.replace(tzinfo=timezone.utc)
                
                # Check cutoff date
                if rev_date and rev_date < cutoff_date:
                    consecutive_old += 1
                    if consecutive_old > 15:
                        stop_locale = True
                        break
                    continue
                else:
                    consecutive_old = 0

                if rev_id and rev_id not in all_scraped_reviews:
                    # Clean & format review record (NEVER store reviewer name or avatar)
                    content = r.get("content") or ""
                    cleaned_record = {
                        "review_id": rev_id,
                        "score": int(r.get("score") or 0),
                        "content": content,
                        "review_created_version": r.get("reviewCreatedVersion"),
                        "app_version": r.get("appVersion"),
                        "at": rev_date.isoformat() if rev_date else datetime.now(timezone.utc).isoformat(),
                        "thumbs_up_count": int(r.get("thumbsUpCount") or 0),
                        "reply_content": r.get("replyContent"),
                        "replied_at": r.get("repliedAt").isoformat() if r.get("repliedAt") else None,
                        "detected_language": detect_language(content),
                        "rating_bucket": compute_rating_bucket(int(r.get("score") or 0))
                    }
                    all_scraped_reviews[rev_id] = cleaned_record
                    if rev_id not in existing_ids:
                        new_reviews.append(cleaned_record)

            if stop_locale or not token:
                break

            # Polite pacing delay
            time.sleep(0.5)

    logger.info(f"Scraped {len(all_scraped_reviews)} total unique reviews in scope ({len(new_reviews)} new).")

    # 2. Save raw backup to disk
    RAW_DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RAW_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(list(all_scraped_reviews.values()), f, ensure_ascii=False, indent=2)
    logger.info(f"Saved raw snapshot to {RAW_DATA_PATH}")

    # 3. Incrementally persist new reviews into SQLite
    if new_reviews:
        conn = get_connection(db_path)
        cur = conn.cursor()
        cur.executemany("""
            INSERT OR IGNORE INTO reviews (
                review_id, score, content, review_created_version, app_version,
                at, thumbs_up_count, reply_content, replied_at, detected_language,
                rating_bucket
            ) VALUES (
                :review_id, :score, :content, :review_created_version, :app_version,
                :at, :thumbs_up_count, :reply_content, :replied_at, :detected_language,
                :rating_bucket
            )
        """, new_reviews)
        conn.commit()
        conn.close()
        logger.info(f"Inserted {len(new_reviews)} new reviews into database.")

    # Get total count in database
    conn = get_connection(db_path)
    cur = conn.cursor()
    total_in_db = cur.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()

    return len(new_reviews), total_in_db

def import_reviews_from_csv(csv_path: str, db_path=None) -> int:
    """Fallback utility: import reviews from CSV if scraping is ever blocked."""
    import pandas as pd
    init_db(db_path)
    df = pd.read_csv(csv_path)
    records = []
    for _, row in df.iterrows():
        rev_id = str(row.get("review_id", row.get("reviewId", "")))
        score = int(row.get("score", row.get("rating", 0)))
        content = str(row.get("content", row.get("text", "")))
        at_val = str(row.get("at", row.get("date", datetime.now(timezone.utc).isoformat())))
        if not rev_id:
            continue
        records.append({
            "review_id": rev_id,
            "score": score,
            "content": content,
            "review_created_version": row.get("review_created_version", row.get("appVersion")),
            "app_version": row.get("app_version", row.get("appVersion")),
            "at": at_val,
            "thumbs_up_count": int(row.get("thumbs_up_count", 0)),
            "reply_content": row.get("reply_content"),
            "replied_at": row.get("replied_at"),
            "detected_language": detect_language(content),
            "rating_bucket": compute_rating_bucket(score)
        })

    conn = get_connection(db_path)
    cur = conn.cursor()
    cur.executemany("""
        INSERT OR IGNORE INTO reviews (
            review_id, score, content, review_created_version, app_version,
            at, thumbs_up_count, reply_content, replied_at, detected_language,
            rating_bucket
        ) VALUES (
            :review_id, :score, :content, :review_created_version, :app_version,
            :at, :thumbs_up_count, :reply_content, :replied_at, :detected_language,
            :rating_bucket
        )
    """, records)
    conn.commit()
    inserted = cur.rowcount
    conn.close()
    return inserted
