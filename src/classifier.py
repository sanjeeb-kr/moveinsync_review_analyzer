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
from google import genai

from google.genai import errors as genai_errors

from config.config import (
    MODEL_NAME, GEMINI_API_KEY, USE_MOCK_AI,
    ALLOWED_ISSUES, ALLOWED_RESPONSIBILITIES, ALLOWED_JOURNEY_STAGES,
    REVIEWS_PER_REQUEST, MAX_RETRIES, DB_PATH
)
from src.db import get_connection
from src.budget import BudgetManager, QuotaExhaustedException, BudgetExceededException
from src.scraper import detect_language

logger = logging.getLogger("classifier")

POS_WORDS_REGEX = re.compile(
    r"\b(good|nice|great|best|super|superb|awesome|excellent|fine|cool|mast|osm|love|useful|helpful|perfect|easy|smooth|wonderful|fab|thanks|thank you|dhanyawad|shukriya)\b",
    re.IGNORECASE
)
NEG_WORDS_REGEX = re.compile(
    r"\b(not|nhi|nahi|bad|worst|bekar|bakwas|late|delay|cancel|issue|problem|hate|slow|hang|crash|driver|poor|cheat|fraud|worst|terrible|pathetic)\b",
    re.IGNORECASE
)

def try_rule_classification(content: str, score: int) -> dict | None:
    """
    Classifies short, obvious positive 4-5 star reviews locally to conserve API budget.
    Returns label dict if matched, otherwise None.
    """
    if score not in (4, 5):
        return None

    text = content.strip()
    if len(text) > 100 or len(text) == 0:
        return None

    # Must contain positive keywords and zero negative keywords
    if POS_WORDS_REGEX.search(text) and not NEG_WORDS_REGEX.search(text):
        return {
            "issue": "positive_feedback",
            "extra_issues": [],
            "responsibility": "not_applicable_positive",
            "journey_stage": "general_app",
            "severity": 1,
            "safety_flag": 0,
            "confidence": 1.0,
            "evidence_quote": text[:100],
            "classification_source": "rule",
            "is_uncertain": 0
        }
    return None


def mock_classify_review(review: dict) -> dict:
    """
    Offline Mock AI classifier for tests and API-key-free execution.
    Inspects review text and rating to produce deterministic, schema-compliant labels.
    """
    content = (review.get("content") or "").strip()
    score = int(review.get("score") or 0)
    lower = content.lower()

    # Default fallback
    if score >= 4:
        return {
            "issue": "positive_feedback",
            "extra_issues": [],
            "responsibility": "not_applicable_positive",
            "journey_stage": "general_app",
            "severity": 1,
            "safety_flag": 0,
            "confidence": 0.95,
            "evidence_quote": content[:60] if content else "Good",
            "classification_source": "mock",
            "is_uncertain": 0
        }

    # Safety checks
    if any(w in lower for w in ["safety", "unsafe", "threat", "harass", "accident", "emergency", "sos", "danger", "touch"]):
        q = next((w for w in ["unsafe", "safety", "threat", "harass", "accident", "emergency"] if w in lower), "")
        quote = content if len(content) < 80 else content[:80]
        return {
            "issue": "safety_complaints",
            "extra_issues": [],
            "responsibility": "operations_fleet",
            "journey_stage": "in-ride",
            "severity": 3,
            "safety_flag": 1,
            "confidence": 0.90,
            "evidence_quote": quote,
            "classification_source": "mock",
            "is_uncertain": 0
        }

    # Login and OTP
    if any(w in lower for w in ["otp", "login", "password", "sign in", "signin", "verification code"]):
        return {
            "issue": "login_and_otp",
            "extra_issues": [],
            "responsibility": "app_technical",
            "journey_stage": "onboarding/login",
            "severity": 2,
            "safety_flag": 0,
            "confidence": 0.88,
            "evidence_quote": content[:60],
            "classification_source": "mock",
            "is_uncertain": 0
        }

    # Tracking & ETA
    if any(w in lower for w in ["track", "tracking", "gps", "map", "live location", "eta", "location wrong"]):
        return {
            "issue": "tracking_and_eta",
            "extra_issues": [],
            "responsibility": "app_technical",
            "journey_stage": "live_tracking",
            "severity": 2,
            "safety_flag": 0,
            "confidence": 0.85,
            "evidence_quote": content[:60],
            "classification_source": "mock",
            "is_uncertain": 0
        }

    # Late pickup / cab
    if any(w in lower for w in ["late", "delay", "delayed", "not arrived", "wait", "waiting", "time pe", "on time"]):
        return {
            "issue": "late_pickup_or_vehicle_assignment",
            "extra_issues": [],
            "responsibility": "operations_fleet",
            "journey_stage": "pickup_time_and_routing",
            "severity": 2,
            "safety_flag": 0,
            "confidence": 0.85,
            "evidence_quote": content[:60],
            "classification_source": "mock",
            "is_uncertain": 0
        }

    # Driver behaviour
    if any(w in lower for w in ["driver", "rude", "rash", "arrogant", "call not receive", "behaviour", "behavior"]):
        return {
            "issue": "driver_behaviour_or_communication",
            "extra_issues": [],
            "responsibility": "operations_fleet",
            "journey_stage": "in-ride",
            "severity": 2,
            "safety_flag": 0,
            "confidence": 0.85,
            "evidence_quote": content[:60],
            "classification_source": "mock",
            "is_uncertain": 0
        }

    # Crashes and slowness
    if any(w in lower for w in ["crash", "freeze", "slow", "hang", "blank", "white screen", "black screen", "loading"]):
        return {
            "issue": "crashes_and_slowness",
            "extra_issues": [],
            "responsibility": "app_technical",
            "journey_stage": "general_app",
            "severity": 2,
            "safety_flag": 0,
            "confidence": 0.85,
            "evidence_quote": content[:60],
            "classification_source": "mock",
            "is_uncertain": 0
        }

    # Booking issues
    if any(w in lower for w in ["book", "booking", "schedule", "roster", "slot"]):
        return {
            "issue": "booking_failure_or_wrong_date",
            "extra_issues": [],
            "responsibility": "app_technical",
            "journey_stage": "booking",
            "severity": 2,
            "safety_flag": 0,
            "confidence": 0.85,
            "evidence_quote": content[:60],
            "classification_source": "mock",
            "is_uncertain": 0
        }

    # Generic complaint
    return {
        "issue": "generic_complaint_with_no_detail",
        "extra_issues": [],
        "responsibility": "unclear",
        "journey_stage": "general_app",
        "severity": 1,
        "safety_flag": 0,
        "confidence": 0.70,
        "evidence_quote": content[:60] if content else "Worst",
        "classification_source": "mock",
        "is_uncertain": 0
    }

def validate_and_sanitize_label(label: dict, original_content: str) -> dict:
    """
    Validates AI output against strict taxonomy:
    - Verifies allowed issue, responsibility, journey_stage
    - Verifies severity in [1, 2, 3] and safety_flag in [0, 1]
    - Checks that evidence_quote is a verbatim substring of original_content
    """
    sanitized = {}

    # Issue
    issue = str(label.get("issue", "")).strip().lower()
    if issue not in ALLOWED_ISSUES:
        # Fallback mapping
        matched_issue = "other"
        for ai in ALLOWED_ISSUES:
            if ai in issue or issue in ai:
                matched_issue = ai
                break
        sanitized["issue"] = matched_issue
    else:
        sanitized["issue"] = issue

    # Extra issues
    extra = label.get("extra_issues", [])
    if isinstance(extra, list):
        sanitized["extra_issues"] = [i for i in extra if i in ALLOWED_ISSUES and i != sanitized["issue"]]
    else:
        sanitized["extra_issues"] = []

    # Responsibility
    resp = str(label.get("responsibility", "")).strip().lower()
    if resp not in ALLOWED_RESPONSIBILITIES:
        sanitized["responsibility"] = "unclear"
    else:
        sanitized["responsibility"] = resp

    # Journey Stage
    stage = str(label.get("journey_stage", "")).strip().lower()
    if stage not in ALLOWED_JOURNEY_STAGES:
        sanitized["journey_stage"] = "general_app"
    else:
        sanitized["journey_stage"] = stage

    # Severity
    try:
        sev = int(label.get("severity", 1))
        sanitized["severity"] = max(1, min(3, sev))
    except Exception:
        sanitized["severity"] = 1

    # Safety flag
    sanitized["safety_flag"] = 1 if bool(label.get("safety_flag")) or sanitized["issue"] == "safety_complaints" else 0
    if sanitized["safety_flag"] == 1:
        sanitized["severity"] = 3

    # Confidence
    try:
        conf = float(label.get("confidence", 0.8))
        sanitized["confidence"] = max(0.0, min(1.0, conf))
    except Exception:
        sanitized["confidence"] = 0.8

    # Evidence quote verbatim verification
    quote = str(label.get("evidence_quote", "")).strip()
    is_uncertain = 0

    if quote and quote.lower() in original_content.lower():
        # Verbatim quote verified
        sanitized["evidence_quote"] = quote
    else:
        # Quote wasn't verbatim; find best snippet or slice first 60 chars
        if len(original_content) <= 80:
            sanitized["evidence_quote"] = original_content.strip()
        else:
            sanitized["evidence_quote"] = original_content.strip()[:60]
        is_uncertain = 1

    sanitized["is_uncertain"] = is_uncertain
    sanitized["classification_source"] = label.get("classification_source", "llm")
    return sanitized

def build_llm_prompt(reviews_batch: list[dict]) -> str:
    """Constructs prompt for Gemini LLM batch classification."""
    reviews_input = []
    for r in reviews_batch:
        reviews_input.append({
            "id": r["review_id"],
            "score": r["score"],
            "text": r["content"],
            "lang": r.get("detected_language", "Unknown")
        })

    prompt = f"""You are an expert product analyst specializing in corporate employee commute software for MoveInSync.
Classify the following customer Play Store reviews into our strict taxonomy.
The text may be in English, Hindi (Devanagari), Hinglish (e.g., 'bhot bekar hai', 'cab time pe nahi aati', 'booking nahi ho rahi hai'), or mixed.
NEVER rewrite the original text. Generic rants like 'worst app' without specifics must be labeled 'generic_complaint_with_no_detail'.
Do not assume root causes if the review only describes a symptom (e.g. 'cab arrived late' is operations_fleet, not app_technical, unless an app bug is explicitly stated).

Allowed 'issue' values (pick 1 main):
{json.dumps(ALLOWED_ISSUES, indent=2)}

Allowed 'responsibility' values:
{json.dumps(ALLOWED_RESPONSIBILITIES, indent=2)}

Allowed 'journey_stage' values:
{json.dumps(ALLOWED_JOURNEY_STAGES, indent=2)}

Severity:
1 = annoying / cosmetic
2 = blocks the task, costs time or money
3 = safety risk, physical threat, or critical system failure

Safety Flag:
1 if any physical safety, driver harassment, late night stranded risk, or danger mentioned; else 0.

Evidence Quote:
Must be an EXACT, VERBATIM substring copied directly from the review's 'text'.

Reviews to classify:
{json.dumps(reviews_input, ensure_ascii=False, indent=2)}

Return ONLY a JSON array with one object per review matching this exact JSON schema:
[
  {{
    "id": "review_id_here",
    "issue": "one_allowed_issue",
    "extra_issues": [],
    "responsibility": "one_allowed_responsibility",
    "journey_stage": "one_allowed_stage",
    "severity": 1,
    "safety_flag": 0,
    "confidence": 0.95,
    "evidence_quote": "exact quote from text"
  }}
]
"""
    return prompt

class ReviewClassifier:
    def __init__(self, db_path=None, model_name=MODEL_NAME, api_key=GEMINI_API_KEY, use_mock=USE_MOCK_AI):
        self.db_path = db_path or DB_PATH
        self.model_name = model_name
        self.api_key = api_key
        self.use_mock = use_mock
        self.budget = BudgetManager(db_path=self.db_path)
        self._client = None

    def _get_client(self):
        if self._client is None and not self.use_mock:
            if not self.api_key:
                raise ValueError("GEMINI_API_KEY is not set. Use mock mode or configure .env")
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def classify_batch_llm(self, batch: list[dict]) -> list[dict]:
        """Calls Gemini API for a single batch of reviews with budget checks and quota guards."""
        if self.use_mock:
            return [mock_classify_review(r) for r in batch]

        # 1. Budget check
        self.budget.check_permission()
        self.budget.record_request_start()

        client = self._get_client()
        prompt = build_llm_prompt(batch)

        last_error = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config={
                        "temperature": 0.1,
                        "response_mime_type": "application/json"
                    }
                )
                raw_text = response.text.strip()
                # Clean possible markdown fence
                if raw_text.startswith("```"):
                    raw_text = re.sub(r"^```(json)?", "", raw_text, flags=re.IGNORECASE).strip()
                    raw_text = re.sub(r"```$", "", raw_text).strip()

                parsed = json.loads(raw_text)
                if not isinstance(parsed, list):
                    raise ValueError(f"Expected JSON list from LLM, got: {type(parsed)}")

                # Map back to reviews by ID
                parsed_by_id = {item.get("id"): item for item in parsed if isinstance(item, dict)}
                results = []
                for r in batch:
                    raw_label = parsed_by_id.get(r["review_id"], {})
                    raw_label["classification_source"] = "llm"
                    validated = validate_and_sanitize_label(raw_label, r["content"])
                    results.append(validated)

                # Record success in persistent ledger
                self.budget.record_request_success(len(batch))
                return results

            except genai_errors.APIError as e:
                err_str = str(e)
                code = getattr(e, "code", None)
                # Check for Quota exhaustion (429, RESOURCE_EXHAUSTED)
                if code == 429 or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                    logger.error(f"Daily API Quota exhausted: {err_str}")
                    self.budget.record_quota_exhausted(err_str)
                    raise QuotaExhaustedException(f"API Quota exhausted (HTTP {code}). Halting.") from e

                # Check for temporary 503 server error
                if code == 503 or "503" in err_str or "high demand" in err_str:
                    logger.warning(f"Temporary 503 server error on attempt {attempt + 1}: {err_str}")
                    if attempt < MAX_RETRIES:
                        time.sleep(3.0 * (attempt + 1))
                        continue
                last_error = e

            except Exception as e:
                logger.error(f"Error during LLM classification attempt {attempt + 1}: {e}")
                last_error = e
                if attempt < MAX_RETRIES:
                    time.sleep(2.0 * (attempt + 1))

        # If all retries failed without quota exhaustion, raise or fallback
        logger.error(f"Batch classification failed after {MAX_RETRIES} retries: {last_error}")
        raise last_error

    def save_classified_reviews(self, classified_records: list[tuple]):
        """Persists classified labels to SQLite immediately."""
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        cur.executemany("""
            UPDATE reviews SET
                is_classified = 1,
                classified_at = ?,
                classification_source = ?,
                issue = ?,
                extra_issues = ?,
                responsibility = ?,
                journey_stage = ?,
                severity = ?,
                safety_flag = ?,
                confidence = ?,
                evidence_quote = ?,
                is_uncertain = ?
            WHERE review_id = ?
        """, classified_records)
        conn.commit()
        conn.close()

    def run_rule_prefilter(self) -> int:
        """Applies local rule filter to obvious positive 4-5 star reviews."""
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        unclassified = cur.execute("""
            SELECT review_id, score, content FROM reviews
            WHERE is_classified = 0 AND score >= 4
        """).fetchall()
        conn.close()

        records_to_update = []
        now_iso = datetime.now(timezone.utc).isoformat()
        for row in unclassified:
            label = try_rule_classification(row["content"], row["score"])
            if label:
                records_to_update.append((
                    now_iso,
                    label["classification_source"],
                    label["issue"],
                    json.dumps(label["extra_issues"]),
                    label["responsibility"],
                    label["journey_stage"],
                    label["severity"],
                    label["safety_flag"],
                    label["confidence"],
                    label["evidence_quote"],
                    label["is_uncertain"],
                    row["review_id"]
                ))

        if records_to_update:
            self.save_classified_reviews(records_to_update)
            logger.info(f"Rule pre-filter classified {len(records_to_update)} positive reviews locally.")

        return len(records_to_update)

    def run_classification_pipeline(self, max_reviews: int = None) -> dict:
        """
        Executes bulk classification honoring strict budget guardrails.
        Work order:
          1. 1-2 star reviews from last 30 days
          2. 1-2 star reviews from older period
          3. 3-star reviews
          4. 4-5 star reviews (remaining)
        """
        # Step A: Local rule classification for short positives
        rule_cnt = self.run_rule_prefilter()

        # Step B: Select reviews in priority order
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        
        # Calculate 30d threshold
        latest_rev_date = cur.execute("SELECT MAX(at) FROM reviews").fetchone()[0]
        if latest_rev_date:
            t30 = (datetime.fromisoformat(latest_rev_date) - timedelta(days=30)).isoformat()
        else:
            t30 = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        query = f"""
            SELECT review_id, score, content, detected_language FROM reviews
            WHERE is_classified = 0
            ORDER BY
                CASE 
                    WHEN score <= 2 AND at >= '{t30}' THEN 1
                    WHEN score <= 2 THEN 2
                    WHEN score = 3 THEN 3
                    ELSE 4
                END,
                at DESC
        """
        unclassified = cur.execute(query).fetchall()
        conn.close()

        total_pending = len(unclassified)
        logger.info(f"Total reviews awaiting classification: {total_pending}")

        if total_pending == 0:
            return {
                "rule_classified": rule_cnt,
                "llm_classified": 0,
                "pending_remaining": 0,
                "quota_stopped": False,
                "message": "All reviews classified."
            }

        reviews_list = [dict(r) for r in unclassified]
        if max_reviews:
            reviews_list = reviews_list[:max_reviews]

        classified_count = 0
        quota_stopped = False
        batch_size = REVIEWS_PER_REQUEST

        for i in range(0, len(reviews_list), batch_size):
            # Check budget before slicing batch
            status = self.budget.get_status()
            if not status["can_proceed"]:
                logger.warning("Halting pipeline: budget limit or quota cooldown active.")
                quota_stopped = True
                break

            batch = reviews_list[i : i + batch_size]
            try:
                labels = self.classify_batch_llm(batch)
            except (QuotaExhaustedException, BudgetExceededException) as e:
                logger.warning(f"Pipeline stopped by budget manager: {e}")
                quota_stopped = True
                break
            except Exception as e:
                logger.error(f"Unexpected error classifying batch: {e}")
                break

            # Persist batch immediately
            now_iso = datetime.now(timezone.utc).isoformat()
            records = []
            for r, l in zip(batch, labels):
                records.append((
                    now_iso,
                    l["classification_source"],
                    l["issue"],
                    json.dumps(l["extra_issues"]),
                    l["responsibility"],
                    l["journey_stage"],
                    l["severity"],
                    l["safety_flag"],
                    l["confidence"],
                    l["evidence_quote"],
                    l["is_uncertain"],
                    r["review_id"]
                ))
            self.save_classified_reviews(records)
            classified_count += len(batch)
            logger.info(f"Classified and saved {classified_count} / {len(reviews_list)} reviews.")

        # Re-check remaining pending
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        pending_remaining = cur.execute("SELECT COUNT(*) FROM reviews WHERE is_classified = 0").fetchone()[0]
        conn.close()

        return {
            "rule_classified": rule_cnt,
            "llm_classified": classified_count,
            "pending_remaining": pending_remaining,
            "quota_stopped": quota_stopped,
            "budget_status": self.budget.get_status()
        }
