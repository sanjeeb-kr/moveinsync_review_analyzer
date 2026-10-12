import os
from pathlib import Path
from dotenv import load_dotenv

# Base Directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file
load_dotenv(BASE_DIR / ".env")

# Play Store Application
APP_ID = os.getenv("APP_ID", "com.moveinsync.ets")
LOCALES = ["en", "hi", "kn", "ta", "te", "mr", "bn", "gu", "pa", "ml"]
DEFAULT_COUNTRY = "in"
DAYS_HISTORY = int(os.getenv("DAYS_HISTORY", "180"))

# AI & LLM Configuration
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY", "")
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.5-flash")
USE_MOCK_AI = os.getenv("USE_MOCK_AI", "false").lower() in ("true", "1", "yes")

# AI Daily Budget Guardrails
MAX_REQUESTS_PER_DAY = int(os.getenv("MAX_REQUESTS_PER_DAY", "16"))
REVIEWS_PER_REQUEST = int(os.getenv("REVIEWS_PER_REQUEST", "40"))
REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "6.0"))
MAX_RETRIES = int(os.getenv("MAX_RETRIES", "2"))

# Database & Data Paths
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "moveinsync.db"
RAW_DATA_PATH = DATA_DIR / "raw_reviews.json"
ACTION_ITEMS_PATH = DATA_DIR / "action_items.csv"
AUDIT_SAMPLE_PATH = BASE_DIR / "audit" / "audit_sample.csv"
REPORTS_DIR = BASE_DIR / "reports"

# Analytics Configuration
TIMEZONE = "Asia/Kolkata"  # IST (UTC+05:30)
MIN_SAMPLE_FOR_TREND = 15
PROVISIONAL_CLASSIFICATION_THRESHOLD = 0.70  # 70% threshold

# Allowed Taxonomy Values
ALLOWED_ISSUES = [
    "booking_failure_or_wrong_date",
    "confusing_booking_confirmation",
    "login_and_otp",
    "account_setup_and_onboarding",
    "crashes_and_slowness",
    "tracking_and_eta",
    "route_planning_and_trip_assignment",
    "late_pickup_or_vehicle_assignment",
    "driver_behaviour_or_communication",
    "check_in_and_no_show_disputes",
    "enterprise_roster_or_transport_configuration",
    "safety_complaints",
    "positive_feedback",
    "generic_complaint_with_no_detail",
    "feature_request_or_usability",
    "other"
]

ALLOWED_RESPONSIBILITIES = [
    "app_technical",
    "operations_fleet",
    "enterprise_configuration",
    "mixed",
    "unclear",
    "not_applicable_positive"
]

ALLOWED_JOURNEY_STAGES = [
    "onboarding/login",
    "roster/shift",
    "booking",
    "pickup_time_and_routing",
    "live_tracking",
    "boarding/otp",
    "in-ride",
    "drop",
    "support",
    "notifications",
    "general_app"
]
