# MoveInSync Play Store Rating Diagnosis & Improvement System

> **A reproducible, production-grade diagnostic pipeline and recommendations engine built for MoveInSync (`com.moveinsync.ets`).**  
> Identifies why Play Store ratings drop, categorizes root causes (App Technical vs Fleet Operations vs Enterprise Policy), computes simulated Star Lift scenarios, and provides engineering-ready sprint specifications and an interactive dashboard.

---

## ⚡ 5-Minute Quickstart Guide

If you have 5 minutes to evaluate the project findings:

1. **Read the Executive Memo (2 Minutes):**  
   Open [`reports/executive_memo.pdf`](reports/executive_memo.pdf).  
   It summarizes the core findings, the -0.79★ gap between text reviews (3.81★) and official India listing score (4.6★), the top ranked friction drivers, what to fix in the first 14 days, and what internal company telemetry is needed.

2. **Explore the Interactive Dashboard (2 Minutes):**  
   Start the local Flask dashboard:
   ```powershell
   .venv\Scripts\python app.py
   ```
   Open your browser at [http://127.0.0.1:5000](http://127.0.0.1:5000):
   - **Overview:** Visualizes rating distributions, version regressions (v12.14.0 lowest at 3.37★), and IST peak commute times.
   - **Issues & Impact:** Explores ranked problem clusters, responsibility splits, and verbatim quotes.
   - **Review Explorer:** Filter 1,527 real Play Store reviews by rating, issue, app version, language (English, Hinglish, Hindi), and quotes.
   - **Actions & Health:** Tracks engineering sprint items and daily API budget usage.

3. **Read the Methodology & Governance Note (1 Minute):**  
   Review [`reports/methodology_note.md`](reports/methodology_note.md) for data collection parameters, sampling limitations, and the persistent budget guardrails.

---

## 🏗️ System Architecture

```mermaid
flowchart TD
    subgraph Data Layer
        PlayScraper[google-play-scraper\n180 Days, 10 Indian Locales] --> RawJSON[(data/raw_reviews.json)]
        RawJSON --> SQLiteDB[(data/moveinsync.db\nreviews + listing_metrics + api_budget)]
    end

    subgraph Analytical Core
        SQLiteDB --> StatEngine[Non-AI Pandas Engine\nVersion degradation, IST shifts, 0.71% reply rate]
        SQLiteDB --> Classifier[Classification Engine\nLocal Rule Pre-Filter + Gemini LLM + Mock AI]
        Classifier --> BudgetMgr[Persistent SQLite Budget Manager\n16 Reqs/Day, >=6s Pacing, 429 Quota Guard]
        StatEngine --> Ranker[Priority & Impact Ranker\nStar Impact Scenarios, Severity, Effort Matrix]
        Classifier --> Ranker
    end

    subgraph Stakeholder Deliverables
        Ranker --> MemoPDF[Executive Memo PDF\nReportLab]
        Ranker --> AnalysisPDF[Analysis & Evidence PDF\nMatplotlib Charts]
        Ranker --> ActionPDF[Action Plan & Sprint Specs PDF]
        Ranker --> JiraCSV[Jira / Linear Tasks CSV\ndata/action_items.csv]
        Ranker --> FlaskDash[Flask Web Dashboard\n4 Pages: Overview, Issues, Explorer, Health]
        Ranker --> DigestMD[Weekly Digest\nreports/weekly_digest.md]
    end
```

---

## 📦 What Was Built & File Structure

```text
movein/
├── app.py                      # Flask Dashboard application (4 pages, zero-AI navigation)
├── run_report.py               # Single-command automated pipeline runner
├── audit_score.py              # Ground-truth accuracy benchmarking script
├── Procfile                    # Deployment entry point for Render / Heroku
├── render.yaml                 # One-click Render Blueprint spec
├── requirements.txt            # Python dependencies (includes gunicorn)
├── pytest.ini                  # Pytest configuration
├── .env.example                # Configuration template
├── .gitignore                  # Git privacy & secrets exclusion rules
├── config/
│   ├── config.py               # Centralized configuration & taxonomy constants
│   └── ranking_weights.json    # Problem ranking weights & formulas
├── src/
│   ├── __init__.py
│   ├── db.py                   # SQLite database initialization & connection management
│   ├── scraper.py              # Incremental scraper (10 locales, language detection, privacy)
│   ├── analysis.py             # Non-AI statistical analytics engine
│   ├── budget.py               # Persistent daily budget manager with 429 quota backoff
│   ├── classifier.py           # Rule pre-filter, Gemini LLM adapter, and offline mock
│   ├── recommender.py          # Star impact scenarios, ranking, and Jira CSV exporter
│   └── pdf_generator.py        # ReportLab PDF and markdown report generator
├── templates/
│   ├── base.html               # Shared layout template
│   ├── overview.html           # Page 1: Executive KPI overview & charts
│   ├── issues.html             # Page 2: Problem diagnostics & responsibility splits
│   ├── explorer.html           # Page 3: Searchable review explorer with quote inspection
│   └── health.html             # Page 4: Action item tracker & API quota gauges
├── scripts/
│   ├── setup_scheduler.bat     # Windows Task Scheduler registration script
│   └── setup_scheduler.ps1     # PowerShell Task Scheduler script
├── data/
│   ├── moveinsync.db           # SQLite database
│   ├── raw_reviews.json        # Raw scraped JSON snapshot
│   └── action_items.csv        # Jira/Linear exportable action items
├── reports/
│   ├── executive_memo.pdf      # 2-Page C-Level Executive Brief
│   ├── analysis_report.pdf     # Detailed Visual Charts & Review Evidence PDF
│   ├── action_plan.pdf         # Engineering Product Specs & Sprint Roadmap PDF
│   ├── methodology_note.md     # Methodology, assumptions & limitations
│   ├── weekly_digest.md        # Stakeholder weekly sync digest
│   └── charts/                 # Generated analytical PNG charts
├── audit/
│   └── audit_sample.csv        # 100-review sample for human accuracy evaluation
└── tests/
    ├── test_scraper_and_db.py  # Scraper, language detection, duplicate handling
    ├── test_classifier_and_budget.py # Quota stops, budget limits, taxonomy validation
    ├── test_analysis_and_recommender.py # Star impact formula, statistical calculations
    └── test_dashboard_routes.py # Flask endpoints and download routes
```

---

## 📊 Summary of Actual Dataset & Findings

### 1. Actual Numbers & Collection Counts
- **Total Reviews in Scope (Last 180 Days):** 1,527 reviews across 10 Indian locales (`en`, `hi`, `kn`, `ta`, `te`, `mr`, `bn`, `gu`, `pa`, `ml`).
- **Official Listing Rating (India):** 4.6★ (114,880 lifetime ratings).
- **Text Review Average:** 3.81★ (Rating gap: -0.79★ vs official listing).
- **Distribution:** 
  - 5★: 985 reviews (64.5%)
  - 1★: 383 reviews (25.1%)
  - 4★: 78 reviews (5.1%)
  - 3★: 42 reviews (2.7%)
  - 2★: 39 reviews (2.6%)
- **Total Low-Star Reviews (1–2★):** 422 reviews.
- **Classification Coverage:**
  - Classified Reviews: 1,442 / 1,527 (94.4% of total dataset).
  - Classified Low-Star Reviews (1–2★): **422 / 422 (100.0% coverage — CONFIRMED)**.
  - Classified by Local Rule Pre-Filter: 832 reviews (zero API budget cost).
  - Classified by Gemini LLM (`gemini-3.5-flash-lite`): 610 reviews.
  - Pending reviews: 85 (remaining non-critical 4-5 star positive sample).
- **Developer Reply Rate on 1–2★ Reviews:** Only **0.71%** (99.3% of dissatisfied users are unanswered).
- **Release Degradation:** Version `12.14.0` was the worst release ($N \ge 15$), averaging only **3.37★** with a 39.5% low-star rate.

### 2. Ranked Problems & Simulated Star Lift Scenarios
1. **Login & OTP (`app_technical` | Small Effort):**
   - 39 low-star reviews (9.24% of all 422 low-star reviews; 45 reviews total).
   - Scenario Star Lift: **+0.079★**.
   - Root Cause Hypothesis: SMS gateway delivery timeouts (> 60s) locking out employees before shifts.
   - Proposed Fix: Multi-channel OTP fallback (WhatsApp & Email) after 30s + Android SMS Retriever API.
2. **Feature Request & Usability (`app_technical` | Small Effort):**
   - 74 reviews (12.1% of low-star).
   - Scenario Star Lift: **+0.101★**.
   - Review Evidence: Annoying friction points like popups blocking OTP viewing.
3. **Booking Failure or Wrong Date (`app_technical` | Medium Effort):**
   - 29 reviews (6.4% of low-star).
   - Scenario Star Lift: **+0.050★**.
   - Root Cause Hypothesis: Roster sync timeouts and opaque cutoff policies causing silent booking rejections.
   - Proposed Fix: Clear inline policy countdowns and actionable error modal dialogs.
4. **Route Planning & Trip Assignment (`operations_fleet` | Large Effort):**
   - Inefficient clustering across long routes.
5. **Late Pickup & Vehicle Assignment (`operations_fleet` | Large Effort):**
   - Driver delays and erratic ETAs.
   - Proposed Fix: Proactive push notification when cab is delayed by > 5 minutes with real-time recalculated ETA and 1-tap transport escalation.

---

## 🧪 Automated Test Results

The comprehensive test suite runs with **zero real API calls** and uses clearly labelled synthetic fixtures:

```powershell
.venv\Scripts\pytest -v
```

**Results:**
- `test_star_impact_scenario_calculation`: **PASSED**
- `test_basic_numbers_and_thresholds`: **PASSED**
- `test_action_items_csv_export`: **PASSED**
- `test_taxonomy_validation`: **PASSED**
- `test_verbatim_quote_validation`: **PASSED**
- `test_rule_prefilter`: **PASSED**
- `test_budget_daily_limit`: **PASSED**
- `test_quota_exhaustion_immediate_stop`: **PASSED**
- `test_resume_after_interruption_no_reprocessing`: **PASSED**
- `test_dashboard_routes`: **PASSED**
- `test_rating_buckets`: **PASSED**
- `test_language_detection`: **PASSED**
- `test_db_init_and_incremental_insert`: **PASSED**
- `test_csv_import_fallback`: **PASSED**

**Status:** `14 passed in 3.56s` (100% pass rate).

---

## 💻 Exact Commands to Run

### 1. Environment Setup
```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment (`.env`)
Copy the example template:
```powershell
copy .env.example .env
```
Ensure `.env` contains:
```ini
GEMINI_API_KEY=your_api_key_here
MODEL_NAME=gemini-3.5-flash-lite
APP_ID=com.moveinsync.ets
DAYS_HISTORY=180
MAX_REQUESTS_PER_DAY=16
REVIEWS_PER_REQUEST=40
REQUEST_DELAY_SECONDS=6.0
MAX_RETRIES=2
```

### 3. Re-run Pipeline (Single Command)
```powershell
.venv\Scripts\python run_report.py
```
This command:
- Checks Google Play Store for new reviews and saves only incremental reviews.
- Checks pending reviews and classifies them within the remaining daily budget.
- Calculates statistical analytics and problem rankings.
- Generates `reports/executive_memo.pdf`, `reports/analysis_report.pdf`, `reports/action_plan.pdf`, `data/action_items.csv`, and `reports/weekly_digest.md`.

### 4. Run Interactive Dashboard
```powershell
.venv\Scripts\python app.py
```
Navigate to `http://127.0.0.1:5000`. Navigating the dashboard never makes API calls.

### 5. Run Human Audit Benchmarking
```powershell
.venv\Scripts\python audit_score.py
```

---

## 🚀 Deploy to GitHub & Render (2-Minute Guide)

### Step A: Push to Your GitHub Repository
1. In PowerShell, add the files and make your initial commit:
   ```powershell
   git add .
   git commit -m "feat: initial commit - MoveInSync Play Store Review Intelligence"
   ```
2. Create a new repository on [GitHub](https://github.com/new) (e.g. `moveinsync-pulse`).
3. Link and push:
   ```powershell
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/moveinsync-pulse.git
   git push -u origin main
   ```

### Step B: Deploy Live on Render (Free Tier)
1. Go to [render.com](https://render.com) and click **New + > Web Service**.
2. Connect your GitHub repository `moveinsync-pulse`.
3. Render automatically reads `render.yaml` or you can configure:
   - **Environment:** `Python`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
4. Click **Deploy Web Service**.
5. Your dashboard is live! It comes pre-loaded with all 1,530 analyzed reviews and charts without requiring any external API calls or scraper setups on Render.

---

## 🛡️ Budget & Quota Guardrails

| Guardrail | Setting | Behavior |
|---|---|---|
| **Max Requests / Day** | `16` | Enforced in persistent SQLite table `api_budget`. Halts when reached. |
| **Reviews / Request** | `40` | Optimizes token context and API efficiency. |
| **Request Pacing** | `6.0s` | Prevents bursts and rate-limit triggers. |
| **Max Retries** | `2` | Exponential backoff for temporary 503 errors. |
| **429 Quota Exhaustion** | Immediate Stop | Instantly halts all AI work, logs cooldown until 00:00 UTC, preserves all data. |
| **Rule Pre-Filter** | Local | Classified 832 positive reviews with zero API cost. |

---

## ⚠️ Known Limitations & Assumptions

1. **Voluntary Response Bias:** Text reviews represent dissatisfied commuters seeking escalation; they are not a representative sample of all 1.5M daily corporate commuters.
2. **Symptom vs Root Cause:** Public reviews describe symptoms ("cab arrived late"); validating whether delays were caused by dispatch algorithms, traffic, or driver no-shows requires internal MoveInSync telemetry.
3. **Accuracy Calibration:** Automated LLM labels are validated for schema compliance and verbatim quote existence. Accuracy on human gold-standard labels is marked as "Accuracy not measured" until `audit/audit_sample.csv` is manually labeled.

---

## 🔧 Optional Actions for the User

1. **Review Executive Memo PDF:** Open `reports/executive_memo.pdf` for executive presentation.
2. **Inspect Dashboard:** Open `http://127.0.0.1:5000` to interactively filter reviews.
3. **Fill Human Audit Benchmark:** Open `audit/audit_sample.csv`, fill in the `human_issue` column for the 100 sample reviews, and run `python audit_score.py` to calculate exact precision metrics.
4. **Enable Windows Scheduled Task:** Run `schtasks /Change /TN "MoveInSync_Daily_Report" /ENABLE` if automated 06:00 AM daily sync is desired.
