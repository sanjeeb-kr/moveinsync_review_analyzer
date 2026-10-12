# Methodology Note: MoveInSync Play Store Rating Analysis

Generated: 2026-10-12 21:40:02  
Author: Forward Deployed Engineering (MoveInSync Evaluation)

---

## 1. Data Collection & Extraction
- **Target Application:** `com.moveinsync.ets` (MoveInSync Employee Cab & Commute App).
- **Official Listing Score (India):** **4.64★** (114,879 lifetime ratings, retrieved via official Play Store package listing for India `country='in'`).
- **Tooling:** Unofficial Play Store scraper library `google-play-scraper` (v1.2.7). Note: Unofficial scraper endpoints simulate Play Store regional client requests and do not guarantee 100% extraction of all historical reviews.
- **Scope & Locales:** Last 180 days across 10 Indian locales (`en`, `hi`, `kn`, `ta`, `te`, `mr`, `bn`, `gu`, `pa`, `ml`).
- **Idempotency & Deduplication:** All scraped records are deduplicated by `review_id`. Total collected dataset: 1,530 reviews.
- **Privacy Enforcement:** In compliance with privacy guidelines, reviewer names and profile pictures are completely excluded from database persistence.
- **Listing Metrics vs Review Average:** The official listing rating, total ratings count, and star histogram are recorded in a dedicated table (`listing_metrics`). They are never conflated with the arithmetic mean of text reviews.

---

## 2. Tools & Stack Used
- **Data Ingestion:** `google-play-scraper` 1.2.7 (unofficial API).
- **Storage:** SQLite (`data/moveinsync.db`) with tables `reviews`, `listing_metrics`, and `api_budget`.
- **Analytical Core:** Python 3, `pandas`, `numpy` for baseline distributions, monthly aggregations, and rolling windows.
- **AI Classification Engine:** Google Gemini (`gemini-3.5-flash-lite` via the official `google-genai` SDK) with strict taxonomy validation, verbatim quote verification, and multilingual handling (English, Devanagari Hindi, Hinglish).
- **Visualization & Reporting:** `matplotlib` and `ReportLab` for automated PDF generation.
- **Dashboard:** `Flask` and `Chart.js` with responsive client-side controls and `READ_ONLY` quota protection.
- **AI Coding Agent:** Antigravity (Google DeepMind agentic coding system) used for engineering development and auditing.

---

## 3. Classification Architecture & Budget Guardrails
- **Pre-Filtering (Rule-Based):** Short, unambiguous 4–5 star positive reviews are categorized locally with zero API cost.
- **Persistent Daily Quota Management:** SQLite ledger (`api_budget`) enforces a maximum of 16 requests/day, 40 reviews/request, and >= 6s delay.
- **Quota Backoff:** Upon encountering HTTP 429 (`RESOURCE_EXHAUSTED`), the pipeline halts instantly and saves all progress.
- **Audit Benchmark:** Accuracy is reported as *'Accuracy not measured on human labels'* unless `audit_score.py` gold-standard audit is run. Classification coverage is reported as 100.0% of low-star reviews (422/422).
- **Regeneration Integrity:** Analytical narratives are written from the computed data structure, and all numbers regenerate identically with `python run_report.py`.

---

## 4. Star Impact Scenario & Priority Ranking
- **Denominators Defined:**
  - *Total text reviews* ($N = 1,530$): Denominator for overall dataset average, star distribution, and scenario lift calculations.
  - *Low-star reviews* ($N = 422$ reviews with 1–2 stars): Denominator for issue-specific low-star share (`share_of_low_star` = issue low-star reviews / 422).
- **Star Impact Formula:**
  Scenario Star Lift = (Sum of deficits: (4 - rating) for all reviews below 4 stars in issue) / Total Reviews.
  *Caveat:* This is an illustrative simulation scenario, not a guarantee of official Google Play score movement.
- **Ranking Function:**
  Score = (Severity * Volume * TrendFactor * StarImpact) / Effort.
  *Note:* Rank scores within a few points are effectively tied. Safety complaints bypass score ranking as an immediate operational escalation block.
