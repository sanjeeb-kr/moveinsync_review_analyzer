#!/usr/bin/env python3
"""
MoveInSync AI Classification Accuracy Evaluator
Compares human ground-truth labels in audit/audit_sample.csv with AI model labels in SQLite.
Also provides sample generation via `python audit_score.py --generate`.
"""

import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import sqlite3
import pandas as pd
from config.config import DB_PATH, AUDIT_SAMPLE_PATH
from src.db import get_connection

def generate_audit_sample(n: int = 100, output_path=None):
    """
    Creates an audit sample CSV with 100 reviews (stratified by ratings and languages)
    WITHOUT AI labels, providing blank columns for human evaluation.
    """
    if output_path is None:
        output_path = AUDIT_SAMPLE_PATH

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(DB_PATH)
    
    # Stratified selection: include all non-English reviews
    non_en_df = pd.read_sql("SELECT review_id, score, content, app_version, detected_language FROM reviews WHERE detected_language != 'English'", conn)
    n_non_en = len(non_en_df)
    
    # Mix of low, medium, and high stars
    low_cnt = max(10, 50 - n_non_en)
    low_df = pd.read_sql(f"SELECT review_id, score, content, app_version, detected_language FROM reviews WHERE score <= 2 AND detected_language = 'English' ORDER BY RANDOM() LIMIT {low_cnt}", conn)
    med_df = pd.read_sql("SELECT review_id, score, content, app_version, detected_language FROM reviews WHERE score = 3 AND detected_language = 'English' ORDER BY RANDOM() LIMIT 20", conn)
    rem_high = max(10, n - (n_non_en + len(low_df) + len(med_df)))
    high_df = pd.read_sql(f"SELECT review_id, score, content, app_version, detected_language FROM reviews WHERE score >= 4 AND detected_language = 'English' ORDER BY RANDOM() LIMIT {rem_high}", conn)
    conn.close()

    sample_df = pd.concat([non_en_df, low_df, med_df, high_df], ignore_index=True)
    sample_df = sample_df.sample(frac=1.0, random_state=42).reset_index(drop=True)

    # Empty columns for human gold standard
    sample_df["human_issue"] = ""
    sample_df["human_responsibility"] = ""
    sample_df["human_journey_stage"] = ""
    sample_df["human_severity"] = ""
    sample_df["human_safety_flag"] = ""
    sample_df["human_notes"] = ""

    sample_df.to_csv(output_path, index=False, encoding="utf-8")
    print(f"Audit sample of {len(sample_df)} reviews written to {output_path}")

def evaluate_accuracy(audit_path=None, db_path=None):
    audit_file = Path(audit_path or AUDIT_SAMPLE_PATH)
    if not audit_file.exists():
        print(f"Audit file not found at {audit_file}. Generating fresh sample...")
        generate_audit_sample(100, audit_file)

    audit_df = pd.read_csv(audit_file)
    filled_human = audit_df["human_issue"].dropna()
    filled_human = filled_human[filled_human.astype(str).str.strip() != ""]

    if len(filled_human) == 0:
        print("=" * 60)
        print("ACCURACY EVALUATION: Accuracy not measured")
        print("=" * 60)
        print(f"Reason: No human ground-truth labels found in '{audit_file}'.")
        print("To evaluate model accuracy:")
        print("  1. Open audit/audit_sample.csv in Excel or Sheets.")
        print("  2. Fill in the 'human_issue', 'human_responsibility', and 'human_journey_stage' columns.")
        print("  3. Re-run: python audit_score.py")
        print("=" * 60)
        return

    # Load corresponding AI labels from DB
    conn = get_connection(db_path or DB_PATH)
    review_ids = tuple(audit_df["review_id"].tolist())
    query = f"SELECT review_id, issue, responsibility, journey_stage, severity, safety_flag FROM reviews WHERE review_id IN ({','.join(['?']*len(review_ids))})"
    ai_df = pd.read_sql(query, conn, params=review_ids)
    conn.close()

    merged = pd.merge(audit_df, ai_df, on="review_id", suffixes=("_human", "_ai"))
    evaluated = merged[merged["human_issue"].astype(str).str.strip() != ""].copy()
    total_eval = len(evaluated)

    print("=" * 60)
    print(f"AI CLASSIFICATION ACCURACY BENCHMARK (N = {total_eval} human-labeled reviews)")
    print("=" * 60)

    # Issue Accuracy
    issue_match = (evaluated["human_issue"].astype(str).str.strip().str.lower() == evaluated["issue"].astype(str).str.strip().str.lower()).sum()
    issue_acc = round(issue_match / total_eval * 100, 2)
    print(f"Issue Classification Accuracy:        {issue_acc}% ({issue_match}/{total_eval})")

    # Responsibility Accuracy
    if "human_responsibility" in evaluated.columns:
        eval_resp = evaluated[evaluated["human_responsibility"].astype(str).str.strip() != ""]
        if not eval_resp.empty:
            resp_match = (eval_resp["human_responsibility"].astype(str).str.strip().str.lower() == eval_resp["responsibility"].astype(str).str.strip().str.lower()).sum()
            resp_acc = round(resp_match / len(eval_resp) * 100, 2)
            print(f"Responsibility Classification Acc:   {resp_acc}% ({resp_match}/{len(eval_resp)})")

    # Journey Stage Accuracy
    if "human_journey_stage" in evaluated.columns:
        eval_stage = evaluated[evaluated["human_journey_stage"].astype(str).str.strip() != ""]
        if not eval_stage.empty:
            stage_match = (eval_stage["human_journey_stage"].astype(str).str.strip().str.lower() == eval_stage["journey_stage"].astype(str).str.strip().str.lower()).sum()
            stage_acc = round(stage_match / len(eval_stage) * 100, 2)
            print(f"Journey Stage Classification Acc:    {stage_acc}% ({stage_match}/{len(eval_stage)})")

    # Safety Flag Match
    if "human_safety_flag" in evaluated.columns:
        eval_safe = evaluated[evaluated["human_safety_flag"].astype(str).str.strip() != ""]
        if not eval_safe.empty:
            safe_match = (eval_safe["human_safety_flag"].astype(int) == eval_safe["safety_flag"].astype(int)).sum()
            safe_acc = round(safe_match / len(eval_safe) * 100, 2)
            print(f"Safety Flag Agreement:               {safe_acc}% ({safe_match}/{len(eval_safe)})")

    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--generate":
        generate_audit_sample()
    else:
        evaluate_accuracy()
