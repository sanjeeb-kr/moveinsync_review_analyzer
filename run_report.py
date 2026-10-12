#!/usr/bin/env python3
"""
MoveInSync Play Store Diagnosis Runner
Single-command pipeline:
1. Incremental review collection from Play Store
2. Updates SQLite database
3. Classifies new reviews within strict daily budget
4. Recalculates statistical analytics and problem rankings
5. Regenerates Executive Memo PDF, Analysis Report PDF, Action Plan PDF, Jira CSV, and Weekly Digest
"""

import sys
import logging
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.config import DB_PATH, REPORTS_DIR, ACTION_ITEMS_PATH
from src.db import init_db, get_connection
from src.scraper import collect_reviews
from src.analysis import load_reviews_df, load_latest_listing_metrics, compute_basic_numbers
from src.classifier import ReviewClassifier
from src.recommender import analyze_problems, export_action_items_csv
from src.pdf_generator import build_all_reports

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_report")

def run_pipeline(force_recalculate: bool = False):
    logger.info("=" * 65)
    logger.info("STARTING MOVEINSYNC PLAY STORE DIAGNOSIS PIPELINE")
    logger.info("=" * 65)

    # 1. Initialize database schema
    init_db(DB_PATH)

    # 2. Incremental data collection
    logger.info("Step 1: Checking for new reviews on Google Play Store...")
    try:
        new_reviews_count, total_reviews = collect_reviews(db_path=DB_PATH)
        logger.info(f"Collection complete: {new_reviews_count} new reviews fetched (Total: {total_reviews}).")
    except Exception as e:
        logger.error(f"Error fetching new reviews from Play Store (continuing with existing data): {e}")
        new_reviews_count = 0

    # 3. Check pending reviews awaiting classification
    conn = get_connection(DB_PATH)
    cur = conn.cursor()
    pending_count = cur.execute("SELECT COUNT(*) FROM reviews WHERE is_classified = 0").fetchone()[0]
    conn.close()

    logger.info(f"Database status: {pending_count} reviews pending classification.")

    # 4. Classify new reviews within strict budget if any exist
    if pending_count > 0:
        logger.info("Step 2: Processing pending reviews through classification pipeline...")
        try:
            classifier = ReviewClassifier(db_path=DB_PATH)
            classify_res = classifier.run_classification_pipeline()
            logger.info(
                f"Classification finished: {classify_res.get('llm_classified', 0)} LLM, "
                f"{classify_res.get('rule_classified', 0)} Rule. Remaining pending: {classify_res.get('pending_remaining', 0)}."
            )
        except Exception as e:
            logger.warning(f"Classification stopped or skipped: {e}")
    else:
        logger.info("No unclassified reviews found; skipping AI classification to conserve quota.")

    # 5. Non-AI statistical numbers & root cause analysis
    logger.info("Step 3: Calculating statistical metrics and ranking root causes...")
    df = load_reviews_df(DB_PATH)
    meta = load_latest_listing_metrics(DB_PATH)
    analysis_res = compute_basic_numbers(df, meta)
    recommender_res = analyze_problems(df)

    # 6. Export Action Items CSV
    csv_path = export_action_items_csv(recommender_res["engineering_specs"], ACTION_ITEMS_PATH)
    logger.info(f"Exported Jira/Linear action items to {csv_path}")

    # 7. Generate all deliverables (PDFs and Markdown notes)
    logger.info("Step 4: Compiling Executive Memo and visual reports...")
    build_all_reports(analysis_res, recommender_res, REPORTS_DIR)

    logger.info("=" * 65)
    logger.info("PIPELINE COMPLETED SUCCESSFULLY!")
    logger.info(f"Listing Rating: {analysis_res['summary']['listing_score']}★ | Text Review Avg: {analysis_res['summary']['avg_text_rating']}★")
    logger.info(f"Top Problem: {recommender_res['ranked_problems'][0]['title']} (+{recommender_res['ranked_problems'][0]['star_impact']['delta']}★ scenario)")
    logger.info(f"Executive Memo generated at: {REPORTS_DIR / 'executive_memo.pdf'}")
    logger.info(f"Weekly Digest generated at:   {REPORTS_DIR / 'weekly_digest.md'}")
    logger.info("=" * 65)

if __name__ == "__main__":
    run_pipeline()
