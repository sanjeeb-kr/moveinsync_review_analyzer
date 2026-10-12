import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import time
import logging
from datetime import datetime, timezone, timedelta
from config.config import (
    MAX_REQUESTS_PER_DAY, REQUEST_DELAY_SECONDS, DB_PATH
)
from src.db import get_connection

logger = logging.getLogger("budget")

class QuotaExhaustedException(Exception):
    """Raised when daily quota limit is hit or API returns 429 Resource Exhausted."""
    pass

class BudgetExceededException(Exception):
    """Raised when daily request budget configured in system is reached."""
    pass

class BudgetManager:
    def __init__(self, db_path=None, max_per_day: int = MAX_REQUESTS_PER_DAY, delay_sec: float = REQUEST_DELAY_SECONDS):
        self.db_path = db_path or DB_PATH
        self.max_per_day = max_per_day
        self.delay_sec = delay_sec

    def _get_today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def get_status(self) -> dict:
        """Returns current daily usage, remaining requests, and quota flags."""
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        today = self._get_today_str()
        row = cur.execute("SELECT * FROM api_budget WHERE date = ?", (today,)).fetchone()
        conn.close()

        if not row:
            return {
                "date": today,
                "requests_used": 0,
                "max_requests": self.max_per_day,
                "requests_remaining": self.max_per_day,
                "reviews_classified": 0,
                "quota_exhausted": False,
                "cooldown_until": None,
                "last_error": None,
                "can_proceed": True
            }

        quota_exhausted = bool(row["quota_exhausted"])
        cooldown_until = row["cooldown_until"]
        now_iso = datetime.now(timezone.utc).isoformat()

        is_in_cooldown = False
        if quota_exhausted and cooldown_until:
            if now_iso < cooldown_until:
                is_in_cooldown = True

        requests_used = int(row["request_count"])
        remaining = max(0, self.max_per_day - requests_used)
        can_proceed = (remaining > 0) and not is_in_cooldown

        return {
            "date": today,
            "requests_used": requests_used,
            "max_requests": self.max_per_day,
            "requests_remaining": remaining,
            "reviews_classified": int(row["reviews_classified"]),
            "quota_exhausted": is_in_cooldown,
            "cooldown_until": cooldown_until,
            "last_error": row["last_error"],
            "can_proceed": can_proceed
        }

    def check_permission(self):
        """Raises an exception if calls are not allowed due to budget or quota exhaustion."""
        status = self.get_status()
        if status["quota_exhausted"]:
            msg = f"API Quota exhausted. Cooldown active until {status['cooldown_until']}. Halting requests."
            logger.warning(msg)
            raise QuotaExhaustedException(msg)

        if status["requests_remaining"] <= 0:
            msg = f"Daily budget of {self.max_per_day} requests reached for today ({status['date']}). Halting."
            logger.warning(msg)
            raise BudgetExceededException(msg)

    def record_request_start(self):
        """Checks pacing and updates timestamp."""
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        today = self._get_today_str()
        row = cur.execute("SELECT last_request_at FROM api_budget WHERE date = ?", (today,)).fetchone()
        if row and row["last_request_at"]:
            last_dt = datetime.fromisoformat(row["last_request_at"])
            now_dt = datetime.now(timezone.utc)
            elapsed = (now_dt - last_dt).total_seconds()
            if elapsed < self.delay_sec:
                sleep_needed = self.delay_sec - elapsed
                logger.info(f"Pacing delay: waiting {sleep_needed:.1f}s before next API request...")
                time.sleep(sleep_needed)
        conn.close()

    def record_request_success(self, reviews_in_batch: int):
        """Records successful API request in persistent SQLite ledger."""
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        today = self._get_today_str()
        now_iso = datetime.now(timezone.utc).isoformat()

        cur.execute("""
            INSERT INTO api_budget (date, request_count, reviews_classified, last_request_at, quota_exhausted)
            VALUES (?, 1, ?, ?, 0)
            ON CONFLICT(date) DO UPDATE SET
                request_count = request_count + 1,
                reviews_classified = reviews_classified + ?,
                last_request_at = ?
        """, (today, reviews_in_batch, now_iso, reviews_in_batch, now_iso))
        conn.commit()
        conn.close()
        logger.info(f"Budget recorded: +1 request ({reviews_in_batch} reviews).")

    def record_quota_exhausted(self, error_msg: str, retry_after_seconds: float = None):
        """Immediately sets quota exhaustion flag and cooldown timestamp."""
        conn = get_connection(self.db_path)
        cur = conn.cursor()
        today = self._get_today_str()
        now = datetime.now(timezone.utc)

        if retry_after_seconds and retry_after_seconds > 0:
            cooldown = now + timedelta(seconds=retry_after_seconds)
        else:
            # Default to next day 00:00 UTC
            tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            cooldown = tomorrow

        cooldown_iso = cooldown.isoformat()
        cur.execute("""
            INSERT INTO api_budget (date, request_count, quota_exhausted, cooldown_until, last_error)
            VALUES (?, 1, 1, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                quota_exhausted = 1,
                cooldown_until = ?,
                last_error = ?
        """, (today, cooldown_iso, error_msg, cooldown_iso, error_msg))
        conn.commit()
        conn.close()
        logger.error(f"Quota exhausted recorded! Cooldown until {cooldown_iso}. Error: {error_msg}")
