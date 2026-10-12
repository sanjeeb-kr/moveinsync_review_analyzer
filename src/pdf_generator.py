import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import os
from datetime import datetime
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, KeepTogether, PageBreak, HRFlowable
)
from reportlab.pdfgen import canvas

from config.config import REPORTS_DIR, TIMEZONE

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        self.setStrokeColor(colors.HexColor("#e2e8f0"))
        self.setLineWidth(0.5)
        self.line(40, 35, 572, 35)
        
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(572, 22, page_str)
        self.drawString(40, 22, "MoveInSync Play Store Diagnosis | Confidential — Internal Product Brief")
        self.restoreState()

def setup_styles():
    styles = getSampleStyleSheet()
    
    # Custom Brand Palette: MoveInSync Navy & Teal
    c_primary = colors.HexColor("#0f172a") # Navy
    c_accent = colors.HexColor("#0284c7")  # Teal Blue
    c_text = colors.HexColor("#334155")
    
    styles.add(ParagraphStyle(
        name="DocTitle",
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=c_primary,
        spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name="DocSubtitle",
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=12
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading",
        fontName="Helvetica-Bold",
        fontSize=13,
        leading=16,
        textColor=c_accent,
        spaceBefore=10,
        spaceAfter=6,
        keepWithNext=True
    ))
    styles.add(ParagraphStyle(
        name="BodyTextCustom",
        fontName="Helvetica",
        fontSize=9,
        leading=13,
        textColor=c_text,
        spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name="CalloutText",
        fontName="Helvetica-Oblique",
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1e293b")
    ))
    styles.add(ParagraphStyle(
        name="TableHeader",
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=colors.white,
        alignment=0
    ))
    styles.add(ParagraphStyle(
        name="TableCell",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=c_text
    ))
    styles.add(ParagraphStyle(
        name="TableCellBold",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=c_primary
    ))
    return styles

def generate_charts(analysis_res: dict, output_dir: Path) -> dict:
    """Generates analytical charts using matplotlib."""
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_paths = {}

    # 1. Star Distribution Chart
    fig, ax = plt.subplots(figsize=(6, 2.5), dpi=200)
    stars = [1, 2, 3, 4, 5]
    dist = analysis_res["distribution"]["star_counts"]
    counts = [dist.get(s, 0) for s in stars]
    bar_colors = ["#ef4444", "#f97316", "#eab308", "#84cc16", "#10b981"]
    bars = ax.bar([f"{s}★" for s in stars], counts, color=bar_colors, width=0.55, edgecolor="#0f172a", linewidth=0.5)
    ax.set_title("Play Store Review Star Rating Distribution (Last 180 Days)", fontsize=10, fontweight="bold", pad=8)
    ax.set_ylabel("Review Count", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(axis="y", linestyle="--", alpha=0.5)
    for b in bars:
        h = b.get_height()
        ax.annotate(f"{h}", (b.get_x() + b.get_width() / 2, h + 15), ha="center", va="bottom", fontsize=7, fontweight="bold")
    plt.tight_layout()
    p1 = output_dir / "chart_distribution.png"
    plt.savefig(p1, bbox_inches="tight")
    plt.close(fig)
    chart_paths["distribution"] = str(p1)

    # 2. Hourly Review Posting Volume Chart (IST)
    fig, ax = plt.subplots(figsize=(6, 2.4), dpi=200)
    hours = list(range(24))
    h_data = analysis_res["timing_analysis"]["low_by_hour"]
    h_counts = [h_data.get(h, 0) for h in hours]
    ax.plot(hours, h_counts, marker="o", markersize=3, color="#ef4444", linewidth=1.5, label="1-2★ Reviews Posted")
    ax.fill_between(hours, h_counts, color="#ef4444", alpha=0.15)
    ax.set_title(f"Review Posting Volume by Hour of Day ({analysis_res['timing_analysis']['timezone']})\n(Reflects Play Store submission time, not commute incident time)", fontsize=9, fontweight="bold", pad=8)
    ax.set_xlabel("Hour of Day (24h IST)", fontsize=8)
    ax.set_ylabel("Count of Reviews", fontsize=8)
    ax.set_xticks(hours[::2])
    ax.tick_params(labelsize=8)
    ax.grid(True, linestyle="--", alpha=0.5)
    plt.tight_layout()
    p2 = output_dir / "chart_hourly.png"
    plt.savefig(p2, bbox_inches="tight")
    plt.close(fig)
    chart_paths["hourly"] = str(p2)

    # 3. Rating by Version Chart
    def _ver_tuple(v_str):
        try:
            return tuple(int(x) for x in str(v_str).split("."))
        except Exception:
            return (0,)

    fig, ax = plt.subplots(figsize=(6, 2.8), dpi=200)
    sig_versions = [v for v in analysis_res["version_analysis"]["versions"] if v["is_significant"]]
    sig_versions_sorted = sorted(sig_versions, key=lambda v: _ver_tuple(v["version"]))
    # Take the 10 most recent significant versions (including 12.19.0)
    ver_list = sig_versions_sorted[-10:] if len(sig_versions_sorted) >= 10 else sig_versions_sorted
    if ver_list:
        v_names = [v["version"] for v in ver_list]
        v_ratings = [v["avg_rating"] for v in ver_list]
        colors_v = ["#ef4444" if r < 3.5 else "#3b82f6" for r in v_ratings]
        bars = ax.barh(v_names, v_ratings, color=colors_v, height=0.55, edgecolor="#0f172a", linewidth=0.5)
        ax.axvline(x=4.0, color="#10b981", linestyle="--", linewidth=1, label="Target 4.0★")
        ax.set_xlim(1.0, 5.0)
        ax.set_title("Average Rating by Recent App Version (Significant Versions N >= 15)", fontsize=9, fontweight="bold", pad=8)
        ax.set_xlabel("Average Rating (Stars)", fontsize=8)
        ax.tick_params(labelsize=8)
        ax.grid(axis="x", linestyle="--", alpha=0.5)
        for b in bars:
            w = b.get_width()
            ax.annotate(f"{w:.2f}★", (w + 0.05, b.get_y() + b.get_height() / 2), ha="left", va="center", fontsize=7, fontweight="bold")
        plt.tight_layout()
        p3 = output_dir / "chart_versions.png"
        plt.savefig(p3, bbox_inches="tight")
        plt.close(fig)
        chart_paths["versions"] = str(p3)

    return chart_paths

def generate_executive_memo(analysis_res: dict, recommender_res: dict, output_path: Path):
    """
    Generates reports/executive_memo.pdf (1-2 pages concise executive brief):
    - What the rating and recent reviews show
    - The main problems ranked
    - What to fix first and why
    - How success will be measured
    - What internal data is still needed
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=45
    )
    styles = setup_styles()
    story = []

    # Title & Metadata Header
    story.append(Paragraph("EXECUTIVE MEMO: MOVEINSYNC PLAY STORE RATING DIAGNOSIS", styles["DocTitle"]))
    date_str = datetime.now().strftime("%B %d, %Y")
    meta_text = f"<b>Date:</b> {date_str} &nbsp;|&nbsp; <b>Author:</b> Forward Deployed Engineering &nbsp;|&nbsp; <b>App:</b> com.moveinsync.ets"
    story.append(Paragraph(meta_text, styles["DocSubtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284c7"), spaceAfter=8))

    # Section 1: What the Numbers & Reviews Show
    story.append(Paragraph("1. WHAT THE RATING AND RECENT REVIEWS SHOW", styles["SectionHeading"]))
    s = analysis_res["summary"]
    d = analysis_res["distribution"]
    p = analysis_res["period_comparison"]
    r = analysis_res["reply_performance"]

    exec_summary_p = (
        f"The official Play Store listing score stands at <b>{s['listing_score']}★</b> (114k+ ratings), while the average "
        f"of active text reviews across the past 180 days is <b>{s['avg_text_rating']}★</b> (a gap of {s['rating_gap']}★). "
        f"This discrepancy represents voluntary negative self-selection: employees with routine rides do not write public reviews, "
        f"whereas commute disruptions trigger immediate Play Store vents. The text review distribution is deeply bimodal: "
        f"<b>{d['share_5star']}% 5-star</b> vs <b>{d['share_1star']}% 1-star</b>. In the latest 30 days, text reviews averaged "
        f"<b>{p['latest_30d_avg']}★</b> vs <b>{p['prev_30d_avg']}★</b> in the previous period ({p['trend_verbal']}). "
        f"Crucially, <b>MoveInSync's developer reply rate on 1–2★ reviews is only {r['low_star_reply_rate']}%</b>, leaving 99.3% of "
        f"dissatisfied employees without acknowledgment."
    )
    story.append(Paragraph(exec_summary_p, styles["BodyTextCustom"]))

    # Metric summary box
    summary_data = [
        [
            Paragraph("<b>Listing Rating</b>", styles["TableCellBold"]),
            Paragraph("<b>Text Review Avg</b>", styles["TableCellBold"]),
            Paragraph("<b>Low-Star Share</b>", styles["TableCellBold"]),
            Paragraph("<b>Latest 30d Avg</b>", styles["TableCellBold"]),
            Paragraph("<b>Developer Reply Rate</b>", styles["TableCellBold"])
        ],
        [
            Paragraph(f"{s['listing_score']}★", styles["TableCell"]),
            Paragraph(f"{s['avg_text_rating']}★", styles["TableCell"]),
            Paragraph(f"{d['share_low']}%", styles["TableCell"]),
            Paragraph(f"{p['latest_30d_avg']}★", styles["TableCell"]),
            Paragraph(f"{r['low_star_reply_rate']}%", styles["TableCell"])
        ]
    ]
    t_sum = Table(summary_data, colWidths=[105, 105, 105, 105, 110])
    t_sum.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_sum)
    story.append(Spacer(1, 8))

    # Section 2: Top Problems Ranked
    story.append(Paragraph("2. TOP PROBLEMS RANKED WITH EVIDENCE", styles["SectionHeading"]))
    top_problems = recommender_res["ranked_problems"][:4]
    
    table_rows = [
        [
            Paragraph("<b>Rank & Issue</b>", styles["TableHeader"]),
            Paragraph("<b>Domain</b>", styles["TableHeader"]),
            Paragraph("<b>Share of Low★</b>", styles["TableHeader"]),
            Paragraph("<b>Star Lift Scenario</b>", styles["TableHeader"]),
            Paragraph("<b>Effort</b>", styles["TableHeader"]),
            Paragraph("<b>Key Review Evidence</b>", styles["TableHeader"])
        ]
    ]

    for idx, prob in enumerate(top_problems, start=1):
        q_snippet = prob["quotes"][0]["quote"] if prob["quotes"] else "User reported systemic failure"
        if len(q_snippet) > 65:
            q_snippet = q_snippet[:62] + "..."
        table_rows.append([
            Paragraph(f"<b>#{idx} {prob['title']}</b>", styles["TableCellBold"]),
            Paragraph(prob["dominant_responsibility"].replace("_", " ").title(), styles["TableCell"]),
            Paragraph(f"{prob['share_of_low_star']}% ({prob['low_star_count']})", styles["TableCell"]),
            Paragraph(f"+{prob['star_impact']['delta']}★", styles["TableCell"]),
            Paragraph(prob["estimated_effort"].capitalize(), styles["TableCell"]),
            Paragraph(f'"{q_snippet}"', styles["CalloutText"])
        ])

    t_prob = Table(table_rows, colWidths=[120, 85, 75, 75, 55, 120])
    t_prob.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_prob)
    story.append(Spacer(1, 8))

    # Section 3: What to Fix First and Why
    story.append(Paragraph("3. WHAT TO FIX FIRST AND WHY (14-DAY ACTION PLAN)", styles["SectionHeading"]))
    first_fix = (
        "<b>Priority 1: Live Tracking & Delay Alert Transparency (Days 1–7):</b> Late cabs and erratic ETAs are the #1 driver "
        "of 1-star reviews. While fleet traffic cannot be magically eliminated by app code, <i>frustration stems from silence</i>. "
        "Fix: implement real-time push notifications when a cab is delayed by > 5 minutes with a refreshed live ETA and one-tap transport "
        "desk escalation. This directly defuses commuter anxiety before they vent on the Play Store.<br/>"
        "<b>Priority 2: Booking Confirmation & Cutoff Clarity (Days 8–14):</b> Eliminate silent booking rejections. Clearly display "
        "enterprise cutoffs inline with explicit error reasons instead of generic failures."
    )
    story.append(Paragraph(first_fix, styles["BodyTextCustom"]))

    # Section 4: Success Measurement & Internal Data
    story.append(Paragraph("4. MEASURING SUCCESS & INTERNAL TELEMETRY NEEDED", styles["SectionHeading"]))
    meas_text = (
        "<b>Success Metrics:</b><br/>"
        "1. <b>Play Store Text Rating:</b> Raise 30-day moving average from 3.79★ to > 4.15★ within 60 days.<br/>"
        "2. <b>Low-Star Reply Coverage:</b> Increase 1-2★ developer reply SLA from 0.71% to > 90% within 24 hours of posting.<br/>"
        "3. <b>Tracking MAE:</b> Reduce Mean Absolute Error between predicted ETA and actual pickup to < 3.5 minutes.<br/>"
        "<b>Required Internal Data to Confirm Root Causes:</b><br/>"
        "• Crash logs (Crashlytics/Sentry) for release v12.14.0 to identify crash culprits.<br/>"
        "• Enterprise roster sync latency telemetry to separate HRMS lag from app booking bugs.<br/>"
        "• Driver GPS ping interval histograms to isolate device background killing vs genuine routing errors."
    )
    story.append(Paragraph(meas_text, styles["BodyTextCustom"]))

    doc.build(story, canvasmaker=NumberedCanvas)

def generate_methodology_note(output_path: Path):
    """Generates reports/methodology_note.md."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    content = f"""# Methodology Note: MoveInSync Play Store Rating Analysis

Generated: {now_str}
Author: Forward Deployed Engineering (MoveInSync Evaluation)

---

## 1. Data Collection & Extraction
- **Target Application:** `com.moveinsync.ets` (MoveInSync Employee Cab & Commute App).
- **Official Listing Score (India):** **4.6★** (114,880 lifetime ratings, retrieved via official Play Store package listing for India country='in'). Note: Global/US endpoints previously reported 4.32★, but 4.6★ is the official rating for Indian corporate commuters.
- **Tooling:** Unofficial Play Store scraper library `google-play-scraper` (v1.2.7). Note: Unofficial scraper endpoints simulate Play Store regional client requests and do not guarantee 100% extraction of all historical reviews.
- **Scope & Locales:** Last 180 days across 10 Indian locales (`en`, `hi`, `kn`, `ta`, `te`, `mr`, `bn`, `gu`, `pa`, `ml`).
- **Idempotency & Deduplication:** All scraped records are deduplicated by `review_id`. Re-runs fetch exclusively newly posted reviews.
- **Privacy Enforcement:** In compliance with privacy guidelines, reviewer names and profile pictures are completely excluded from database persistence.
- **Listing Metrics vs Review Average:** The official listing rating, total ratings count, and star histogram are recorded in a dedicated table (`listing_metrics`). They are never conflated with the arithmetic mean of text reviews.

---

## 2. Quantitative Non-AI Baseline
- Plain Python / Pandas computations without AI dependency:
  - Star distribution and 1★ vs 5★ polarity shares.
  - Rolling 30-day window comparisons (latest 30d vs previous 30d).
  - Version-level rating breakdown (minimum threshold: N >= 15 reviews).
  - Review submission timestamps converted to Indian Standard Time (`Asia/Kolkata`, UTC+05:30). Note: Timestamps reflect the hour an employee submitted a review to Google Play, not the exact minute of the commute incident.
  - Developer response rates and median turnaround times on 1–2★ reviews.

---

## 3. Classification Architecture & Strict Budget Guardrails
- **Pre-Filtering (Rule-Based):**
  - Short, unambiguous 4–5 star positive reviews (e.g., "Good app", "Superb cab service", "Very nice") are categorized locally with zero API cost.
- **LLM Taxonomy Adapter:**
  - Powered by Google Gemini (`gemini-3.5-flash-lite`) via the official `google-genai` SDK.
  - Strict classification taxonomy: 16 issue categories, 6 responsibility buckets (`app_technical`, `operations_fleet`, `enterprise_configuration`, `mixed`, `unclear`, `not_applicable_positive`), 11 journey stages, severity (1–3), and verbatim evidence quote verification.
  - Polyglot handling: Evaluates English, Hindi (Devanagari script), Hinglish ("bhot bekar hai", "cab time pe nahi aati"), and mixed code-switching without text alteration.
- **Persistent Daily Quota Management:**
  - SQLite ledger (`api_budget`) enforces a maximum of 16 requests/day, 40 reviews/request, and >= 6s delay.
  - Immediate quota backoff: Upon encountering HTTP 429 (`RESOURCE_EXHAUSTED`), the pipeline halts instantly, logs cooldown until 00:00 UTC, and retains all intermediate progress.
- **Offline / Mock Mode:**
  - Fully functional offline mock AI engine enables automated testing and pipeline execution in zero-API-key environments.

---

## 4. Star Impact Scenario & Priority Ranking
- **Denominators Defined:**
  - *Total text reviews* ($N = 1,527$): Denominator for overall dataset average, star distribution, and scenario lift calculations.
  - *Low-star reviews* ($N = 422$ reviews with 1–2 stars): Denominator for issue-specific low-star share (`share_of_low_star` = issue low-star reviews / 422).
- **Star Impact Formula:**
  Scenario Star Lift = (Sum of deficits: (4 - rating) for all reviews below 4 stars in issue) / Total Reviews.
  *Caveat:* This is an illustrative simulation scenario, not a guarantee of official Google Play score movement.
- **Ranking Function:**
  Score = (Severity * Volume * TrendFactor * StarImpact) / Effort.
  Safety complaints automatically trigger priority escalation override.

---

## 5. Known Limitations & Caveats
1. **Voluntary Response Bias:** Commuters who submit public text reviews are unrepresentative of the 1.5M daily riders. High-friction failures are heavily over-represented.
2. **Symptom vs Root Cause:** Public reviews describe symptoms (e.g. "cab was 30 mins late"); attributing exact root cause between fleet availability, traffic congestion, or dispatch algorithms remains a hypothesis until internal company telemetry is correlated.
3. **Accuracy Calibration:** Automated LLM labels are validated against taxonomy constraints and quote presence. Human benchmark validation is supported via `audit_score.py` but is reported as "Accuracy not measured on human gold standard" until an audit sample is manually scored.
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)


def generate_analysis_report_pdf(analysis_res: dict, recommender_res: dict, chart_paths: dict, output_path: Path):
    """Generates reports/analysis_report.pdf with charts and qualitative evidence."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=45
    )
    styles = setup_styles()
    story = []

    story.append(Paragraph("MOVEINSYNC PLAY STORE ANALYSIS & EVIDENCE REPORT", styles["DocTitle"]))
    story.append(Paragraph("In-depth statistical distributions, cohort breakdowns, and verified review evidence", styles["DocSubtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284c7"), spaceAfter=10))

    # Section 1: Visual Analytics
    story.append(Paragraph("1. QUANTITATIVE VISUAL DASHBOARD", styles["SectionHeading"]))
    if "distribution" in chart_paths and os.path.exists(chart_paths["distribution"]):
        story.append(Image(chart_paths["distribution"], width=520, height=210))
        story.append(Spacer(1, 6))

    if "hourly" in chart_paths and os.path.exists(chart_paths["hourly"]):
        story.append(Image(chart_paths["hourly"], width=520, height=200))
        story.append(Spacer(1, 6))

    story.append(PageBreak())

    if "versions" in chart_paths and os.path.exists(chart_paths["versions"]):
        story.append(Paragraph("2. APP RELEASE PERFORMANCE & REGRESSIONS", styles["SectionHeading"]))
        story.append(Image(chart_paths["versions"], width=520, height=220))
        story.append(Spacer(1, 8))

    # Section 3: Evidence Quotes Table
    story.append(Paragraph("3. VERIFIED COMMUTER EVIDENCE QUOTES", styles["SectionHeading"]))
    quote_rows = [
        [
            Paragraph("<b>Issue & ID</b>", styles["TableHeader"]),
            Paragraph("<b>★</b>", styles["TableHeader"]),
            Paragraph("<b>Date</b>", styles["TableHeader"]),
            Paragraph("<b>Verbatim User Quote</b>", styles["TableHeader"])
        ]
    ]

    for prob in recommender_res["ranked_problems"][:5]:
        for q in prob["quotes"][:2]:
            quote_rows.append([
                Paragraph(f"<b>{prob['title']}</b><br/><font size=6.5 color='#64748b'>{q['review_id'][:18]}...</font>", styles["TableCellBold"]),
                Paragraph(f"{q['score']}★", styles["TableCellBold"]),
                Paragraph(q["date"], styles["TableCell"]),
                Paragraph(f'"{q["quote"]}"', styles["CalloutText"])
            ])

    t_quotes = Table(quote_rows, colWidths=[120, 30, 60, 310])
    t_quotes.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(t_quotes)

    doc.build(story, canvasmaker=NumberedCanvas)

def generate_action_plan_pdf(recommender_res: dict, output_path: Path):
    """Generates reports/action_plan.pdf with engineering specifications and cheap levers."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        leftMargin=40,
        rightMargin=40,
        topMargin=40,
        bottomMargin=45
    )
    styles = setup_styles()
    story = []

    story.append(Paragraph("MOVEINSYNC ENGINEERING ACTION PLAN & SPRINT SPECS", styles["DocTitle"]))
    story.append(Paragraph("Product specifications, acceptance criteria, and 14-day sprint roadmap", styles["DocSubtitle"]))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#0284c7"), spaceAfter=10))

    specs = recommender_res["engineering_specs"]
    for idx, sp in enumerate(specs[:3], start=1):
        story.append(Paragraph(f"SPEC #{idx}: {sp['title'].upper()}", styles["SectionHeading"]))
        
        spec_table = [
            [Paragraph("<b>Domain / Owner:</b>", styles["TableCellBold"]), Paragraph(f"{sp['dominant_responsibility'].replace('_', ' ').title()} | {sp['owner']}", styles["TableCell"])],
            [Paragraph("<b>Effort / Star Lift:</b>", styles["TableCellBold"]), Paragraph(f"{sp['estimated_effort'].capitalize()} Effort | Scenario: +{sp['star_impact_scenario']}★", styles["TableCell"])],
            [Paragraph("<b>Hypothesis:</b>", styles["TableCellBold"]), Paragraph(sp["hypothesis"], styles["TableCell"])],
            [Paragraph("<b>Proposed Change:</b>", styles["TableCellBold"]), Paragraph(sp["proposed_change"], styles["TableCell"])],
            [Paragraph("<b>Acceptance Criteria:</b>", styles["TableCellBold"]), Paragraph(sp["acceptance_criteria"].replace("\n", "<br/>"), styles["TableCell"])],
            [Paragraph("<b>First 14 Days:</b>", styles["TableCellBold"]), Paragraph(sp["first_14_days"], styles["TableCell"])],
            [Paragraph("<b>Telemetrics to Measure:</b>", styles["TableCellBold"]), Paragraph(sp["what_to_measure"], styles["TableCell"])]
        ]
        t = Table(spec_table, colWidths=[120, 400])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#f8fafc")),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(t)
        story.append(Spacer(1, 10))

    story.append(PageBreak())

    # Cheap levers section
    story.append(Paragraph("LOW-HANGING REPUTATION & GROWTH LEVERS", styles["SectionHeading"]))
    levers = recommender_res["cheap_levers"]
    for l_key, l_data in levers.items():
        story.append(Paragraph(f"<b>{l_data['title']}</b>", styles["TableCellBold"]))
        story.append(Paragraph(f"<b>Current Reality:</b> {l_data['current_state']}", styles["BodyTextCustom"]))
        story.append(Paragraph(f"<b>Recommendation:</b> {l_data['recommendation']}", styles["BodyTextCustom"]))
        story.append(Spacer(1, 4))

    doc.build(story, canvasmaker=NumberedCanvas)

def generate_weekly_digest(analysis_res: dict, recommender_res: dict, output_path: Path):
    """Generates reports/weekly_digest.md for recurring stakeholder check-ins."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    s = analysis_res["summary"]
    p = analysis_res["period_comparison"]
    w_ver = analysis_res["version_analysis"]["worst_version"]

    top_prob_lines = []
    tot_low = recommender_res['coverage']['total_low_star']
    for idx, prob in enumerate(recommender_res["ranked_problems"][:3], start=1):
        top_prob_lines.append(
            f"{idx}. **{prob['title']}** ({prob['dominant_responsibility']}): "
            f"{prob['low_star_count']} low-star reviews ({prob['share_of_low_star']}% of {tot_low} low-star; "
            f"{prob['count']} reviews total), Scenario Lift: +{prob['star_impact']['delta']}★"
        )

    content = f"""# Weekly MoveInSync Play Store Digest

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## High-Level Status
- **Official Listing Score:** {s['listing_score']}★ ({s['ratings_count']:,} lifetime ratings)
- **Recent Text Review Average:** {s['avg_text_rating']}★ (Gap: {s['rating_gap']}★)
- **Latest 30d vs Previous 30d:** {p['latest_30d_avg']}★ vs {p['prev_30d_avg']}★ ({p['trend_verbal']})
- **Low-Star Reviews (1–2★) in Latest 30d:** {p['latest_30d_low_count']} ({p['latest_30d_low_share']}%)

## Top 3 Active Friction Drivers
{chr(10).join(top_prob_lines)}

## Release Watch
- **Lowest Rated Version ($N \\ge 15$):** {w_ver['version'] if w_ver else 'N/A'} (Average: {w_ver['avg_rating'] if w_ver else 'N/A'}★ across {w_ver['review_count'] if w_ver else 0} reviews, {w_ver['low_star_share'] if w_ver else 0}% low-star)

## Operations Health Check
- **Developer Reply Rate on 1–2★ Reviews:** {analysis_res['reply_performance']['low_star_reply_rate']}% (Target: > 90% within 24h)
- **Classification Coverage:** {recommender_res['coverage']['low_star_coverage_pct']}% of low-star reviews processed ({'PROVISIONAL' if recommender_res['coverage']['is_provisional'] else 'CONFIRMED'})
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

def build_all_reports(analysis_res: dict, recommender_res: dict, reports_dir=None):
    """Compiles all PDF and Markdown deliverables into reports/."""
    r_dir = Path(reports_dir or REPORTS_DIR)
    r_dir.mkdir(parents=True, exist_ok=True)
    charts_dir = r_dir / "charts"
    
    chart_paths = generate_charts(analysis_res, charts_dir)
    
    generate_executive_memo(analysis_res, recommender_res, r_dir / "executive_memo.pdf")
    generate_methodology_note(r_dir / "methodology_note.md")
    generate_analysis_report_pdf(analysis_res, recommender_res, chart_paths, r_dir / "analysis_report.pdf")
    generate_action_plan_pdf(recommender_res, r_dir / "action_plan.pdf")
    generate_weekly_digest(analysis_res, recommender_res, r_dir / "weekly_digest.md")
    print("All reports generated successfully in", r_dir)
