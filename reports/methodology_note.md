# Methodology Note: MoveInSync Play Store Rating Analysis

Generated: 2026-10-12 13:09:09
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
