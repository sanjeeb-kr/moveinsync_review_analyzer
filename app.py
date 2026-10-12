import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import os
import json
import sqlite3
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, send_file, flash

from config.config import DB_PATH, REPORTS_DIR, ACTION_ITEMS_PATH
from src.db import get_connection, init_db
from src.analysis import load_reviews_df, load_latest_listing_metrics, compute_basic_numbers
from src.recommender import analyze_problems, export_action_items_csv
from src.budget import BudgetManager
from src.classifier import ReviewClassifier
from src.pdf_generator import build_all_reports

app = Flask(__name__)
app.secret_key = "moveinsync-secret-key-fde"
init_db(DB_PATH)

def get_base_data():
    """Loads analyzed data without making any external API calls."""
    df = load_reviews_df(DB_PATH)
    meta = load_latest_listing_metrics(DB_PATH)
    analysis_res = compute_basic_numbers(df, meta)
    recommender_res = analyze_problems(df)
    return df, meta, analysis_res, recommender_res

@app.route("/")
def overview():
    df, meta, analysis_res, recommender_res = get_base_data()
    
    # Ensure reports exist
    if not (REPORTS_DIR / "executive_memo.pdf").exists():
        build_all_reports(analysis_res, recommender_res)

    # Sort by version string using tuple-of-ints key so newer versions always appear.
    # Include all significant versions (N >= 15 reviews) up to 14 entries.
    def _version_key(v_str):
        try:
            return tuple(int(x) for x in str(v_str).split("."))
        except ValueError:
            return (0,)

    versions_data = sorted(
        [v for v in analysis_res["version_analysis"]["versions"] if v["is_significant"]],
        key=lambda v: _version_key(v["version"])
    )[-14:]  # show up to 14 versions, most recent last
    hourly_data = analysis_res["timing_analysis"]["low_by_hour"]

    return render_template(
        "overview.html",
        active_page="overview",
        summary=analysis_res["summary"],
        distribution=analysis_res["distribution"],
        period=analysis_res["period_comparison"],
        reply=analysis_res["reply_performance"],
        timing=analysis_res["timing_analysis"],
        versions_json=json.dumps(versions_data),
        hourly_json=json.dumps(hourly_data)
    )

@app.route("/issues")
def issues():
    df, meta, analysis_res, recommender_res = get_base_data()
    
    # Calculate responsibility and stage breakdown
    df_classified = df[df["is_classified"] == 1]
    resp_counts = df_classified["responsibility"].value_counts().to_dict()
    stage_counts = df_classified["journey_stage"].value_counts().head(8).to_dict()

    return render_template(
        "issues.html",
        active_page="issues",
        coverage=recommender_res["coverage"],
        ranked_problems=recommender_res["ranked_problems"],
        resp_breakdown_json=json.dumps(resp_counts),
        stage_breakdown_json=json.dumps(stage_counts)
    )

@app.route("/explorer")
def explorer():
    score_filter = request.args.get("score", "").strip()
    issue_filter = request.args.get("issue", "").strip()
    resp_filter = request.args.get("responsibility", "").strip()
    version_filter = request.args.get("version", "").strip()
    lang_filter = request.args.get("language", "").strip()
    page = int(request.args.get("page", 1))
    per_page = 25

    conn = get_connection(DB_PATH)
    cur = conn.cursor()

    # Dynamic query filters
    where_clauses = ["1=1"]
    params = []

    if score_filter == "low":
        where_clauses.append("score IN (1, 2)")
    elif score_filter in ("1", "2", "3", "4", "5"):
        where_clauses.append("score = ?")
        params.append(int(score_filter))

    if issue_filter:
        where_clauses.append("issue = ?")
        params.append(issue_filter)

    if resp_filter:
        where_clauses.append("responsibility = ?")
        params.append(resp_filter)

    if version_filter:
        where_clauses.append("app_version = ?")
        params.append(version_filter)

    if lang_filter:
        where_clauses.append("detected_language = ?")
        params.append(lang_filter)

    where_sql = " AND ".join(where_clauses)
    
    # Total count matching
    count_sql = f"SELECT COUNT(*) FROM reviews WHERE {where_sql}"
    total_matching = cur.execute(count_sql, params).fetchone()[0]

    # Paginated rows
    offset = (page - 1) * per_page
    query_sql = f"""
        SELECT * FROM reviews WHERE {where_sql}
        ORDER BY at DESC
        LIMIT {per_page} OFFSET {offset}
    """
    rows = cur.execute(query_sql, params).fetchall()
    reviews_list = [dict(r) for r in rows]

    # Filter dropdown options
    issues_avail = [r[0] for r in cur.execute("SELECT DISTINCT issue FROM reviews WHERE issue IS NOT NULL AND issue != '' ORDER BY issue").fetchall()]
    resp_avail = [r[0] for r in cur.execute("SELECT DISTINCT responsibility FROM reviews WHERE responsibility IS NOT NULL AND responsibility != '' ORDER BY responsibility").fetchall()]
    versions_avail = [r[0] for r in cur.execute("SELECT DISTINCT app_version FROM reviews WHERE app_version IS NOT NULL ORDER BY app_version DESC LIMIT 20").fetchall()]
    langs_avail = [r[0] for r in cur.execute("SELECT DISTINCT detected_language FROM reviews WHERE detected_language IS NOT NULL ORDER BY detected_language").fetchall()]
    conn.close()

    total_pages = max(1, (total_matching + per_page - 1) // per_page)
    
    # Rebuild URL prefix for pagination
    query_params = request.args.to_dict()
    query_params.pop("page", None)
    url_prefix = url_for("explorer", **query_params)
    prefix_sep = "&" if "?" in url_prefix else "?"

    return render_template(
        "explorer.html",
        active_page="explorer",
        reviews=reviews_list,
        total_count=total_matching,
        current_page=page,
        total_pages=total_pages,
        page_url_prefix=f"{url_prefix}{prefix_sep}",
        filter_options={
            "issues": issues_avail,
            "responsibilities": resp_avail,
            "versions": versions_avail,
            "languages": langs_avail
        },
        current_filters={
            "score": score_filter,
            "issue": issue_filter,
            "responsibility": resp_filter,
            "version": version_filter,
            "language": lang_filter
        }
    )

@app.route("/health")
def health():
    df, meta, analysis_res, recommender_res = get_base_data()
    bm = BudgetManager(DB_PATH)
    budget_status = bm.get_status()

    # Ensure action items CSV exists
    if not ACTION_ITEMS_PATH.exists():
        export_action_items_csv(recommender_res["engineering_specs"])

    action_df = pd.read_csv(ACTION_ITEMS_PATH)
    action_items = action_df.to_dict(orient="records")

    conn = get_connection(DB_PATH)
    cur = conn.cursor()
    total_pending = cur.execute("SELECT COUNT(*) FROM reviews WHERE is_classified = 0").fetchone()[0]
    conn.close()

    coverage_dict = dict(recommender_res["coverage"])
    coverage_dict["total_pending"] = total_pending

    msg = request.args.get("msg")

    return render_template(
        "health.html",
        active_page="health",
        budget=budget_status,
        coverage=coverage_dict,
        action_items=action_items,
        message=msg
    )

@app.route("/run_pipeline", methods=["POST"])
def run_pipeline():
    """Manual batch classification trigger from dashboard."""
    classifier = ReviewClassifier(db_path=DB_PATH)
    result = classifier.run_classification_pipeline()
    df, meta, analysis_res, recommender_res = get_base_data()
    build_all_reports(analysis_res, recommender_res)
    export_action_items_csv(recommender_res["engineering_specs"])
    
    msg = f"Processed batch: {result.get('llm_classified', 0)} LLM, {result.get('rule_classified', 0)} Rule. Remaining pending: {result.get('pending_remaining', 0)}."
    return redirect(url_for("health", msg=msg))

@app.route("/download/memo")
def download_memo():
    path = REPORTS_DIR / "executive_memo.pdf"
    if not path.exists():
        df, meta, a, r = get_base_data()
        build_all_reports(a, r)
    return send_file(path, as_attachment=True, download_name="MoveInSync_Executive_Memo.pdf")

@app.route("/download/analysis_pdf")
def download_analysis_pdf():
    path = REPORTS_DIR / "analysis_report.pdf"
    if not path.exists():
        df, meta, a, r = get_base_data()
        build_all_reports(a, r)
    return send_file(path, as_attachment=True, download_name="MoveInSync_Analysis_Report.pdf")

@app.route("/download/action_plan_pdf")
def download_action_plan_pdf():
    path = REPORTS_DIR / "action_plan.pdf"
    if not path.exists():
        df, meta, a, r = get_base_data()
        build_all_reports(a, r)
    return send_file(path, as_attachment=True, download_name="MoveInSync_Action_Plan.pdf")

@app.route("/download/action_items_csv")
def download_action_items_csv():
    if not ACTION_ITEMS_PATH.exists():
        df, meta, a, r = get_base_data()
        export_action_items_csv(r["engineering_specs"])
    return send_file(ACTION_ITEMS_PATH, as_attachment=True, download_name="MoveInSync_Jira_Action_Items.csv")

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
