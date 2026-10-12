import sys
from pathlib import Path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import json
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
from config.config import (
    DB_PATH, ACTION_ITEMS_PATH, PROVISIONAL_CLASSIFICATION_THRESHOLD
)
from src.db import get_connection

DEFAULT_WEIGHTS = {
    "severity_weight": 1.5,
    "volume_weight": 1.2,
    "recent_trend_weight": 1.3,
    "evidence_strength_weight": 1.0,
    "star_impact_weight": 2.0,
    "effort_weights": {"small": 1.0, "medium": 2.0, "large": 3.5},
    "safety_escalation_boost": 100.0
}

def load_weights():
    weights_path = ROOT_DIR / "config" / "ranking_weights.json"
    if weights_path.exists():
        try:
            with open(weights_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_WEIGHTS

def compute_star_impact_scenario(df_all: pd.DataFrame, issue_key: str) -> dict:
    """
    Computes scenario star lift if all reviews for issue_key with rating < 4 were raised to 4.
    Formula: Delta = sum(max(0, 4 - score_i)) / total_reviews
    """
    total_reviews = len(df_all)
    if total_reviews == 0:
        return {"delta": 0.0, "new_avg": 0.0, "affected_count": 0}

    current_avg = float(df_all["score"].mean())
    df_issue = df_all[df_all["issue"] == issue_key]
    low_issue = df_issue[df_issue["score"] < 4]
    
    affected_count = len(low_issue)
    if affected_count == 0:
        return {"delta": 0.0, "new_avg": round(current_avg, 2), "affected_count": 0}

    star_deficit = (4 - low_issue["score"]).sum()
    delta = float(star_deficit) / float(total_reviews)
    new_avg = current_avg + delta

    return {
        "delta": round(delta, 3),
        "current_avg": round(current_avg, 2),
        "new_avg": round(new_avg, 2),
        "affected_count": affected_count,
        "star_deficit": int(star_deficit)
    }

def analyze_problems(df: pd.DataFrame, weights: dict = None) -> dict:
    """
    Synthesizes core problem clusters from classified reviews, ranks them,
    calculates star impact scenarios, and drafts engineering-ready specs.
    """
    if weights is None:
        weights = load_weights()

    total_reviews = len(df)
    total_low = len(df[df["score"].isin([1, 2])])
    classified_low = len(df[(df["score"].isin([1, 2])) & (df["is_classified"] == 1)])
    low_coverage = round(classified_low / total_low * 100, 1) if total_low > 0 else 100.0
    is_provisional = (low_coverage < (PROVISIONAL_CLASSIFICATION_THRESHOLD * 100))

    # Calculate 30-day window
    max_date = df["at_dt"].max() if "at_dt" in df.columns else pd.to_datetime(df["at"], utc=True).max()
    t_30d = max_date - timedelta(days=30)
    t_60d = max_date - timedelta(days=60)

    # Filter only problem issues (exclude pure positive feedback and generic complaint)
    df_classified = df[df["is_classified"] == 1].copy()
    
    # Generic complaint with no detail -> Measurement Gap
    df_generic = df_classified[df_classified["issue"] == "generic_complaint_with_no_detail"]
    gen_cnt = len(df_generic)
    gen_low_cnt = len(df_generic[df_generic["score"].isin([1, 2])])
    gen_share_low = round(gen_low_cnt / total_low * 100, 1) if total_low > 0 else 0.0
    
    measurement_gap = {
        "issue_key": "generic_complaint_with_no_detail",
        "title": "Measurement Gap: Complaints With No Detail",
        "total_reviews": gen_cnt,
        "low_star_count": gen_low_cnt,
        "share_of_low_star": gen_share_low,
        "note": f"{gen_share_low}% of low-star reviews ({gen_low_cnt}/{total_low}) give no reason beyond single-word complaints (e.g. 'worst app', 'bad', 'pathetic').",
        "action": "Implement a one-tap 'what went wrong?' reason picker at trip end. Do not hide or suppress the Play Store rating option, and do not use monetary or ride incentives."
    }

    # Keyword count of update-related crashes and all low-star reviews
    df_low_all = df[df["score"].isin([1, 2])]
    update_pattern = r"update|version|reinstall|uninstall|logout|log out"
    if "content" in df_low_all.columns:
        all_low_kw_cnt = int(df_low_all["content"].str.contains(update_pattern, case=False, na=False).sum())
    else:
        all_low_kw_cnt = 0
    
    # Safety complaints: Split evidence by responsibility
    df_safety = df_classified[df_classified["issue"] == "safety_complaints"]
    safety_low_cnt = len(df_safety[df_safety["score"].isin([1, 2])])
    safety_total_cnt = len(df_safety)
    safety_impact = compute_star_impact_scenario(df, "safety_complaints")

    safety_app_evidence = []
    safety_ops_evidence = []
    for _, r in df_safety.iterrows():
        ev = {
            "review_id": r["review_id"],
            "score": int(r["score"]),
            "responsibility": r.get("responsibility", "operations_fleet"),
            "quote": str(r.get("evidence_quote") or r["content"]).strip(),
            "date": str(r["at"])[:10]
        }
        # Split: SOS blocked by notification pop-ups is app_technical bug
        if "sos" in ev["quote"].lower() or "pop up" in ev["quote"].lower() or ev["responsibility"] == "app_technical":
            safety_app_evidence.append(ev)
        else:
            safety_ops_evidence.append(ev)

    safety_escalation = {
        "title": "Safety & Critical Incident Escalation",
        "total_reviews": safety_total_cnt,
        "low_star_count": safety_low_cnt,
        "share_of_low_star": round(safety_low_cnt / total_low * 100, 1) if total_low > 0 else 0.0,
        "star_impact": safety_impact,
        "note": "Safety complaints bypass score ranking and are tracked as an immediate operational & engineering escalation block.",
        "app_technical_evidence": safety_app_evidence,
        "operations_fleet_evidence": safety_ops_evidence,
        "action_summary": "Fix SOS button access on trip screen (remove blocking popups), audit vendor driver background checks, and route safety flags directly to 24/7 security control room."
    }

    # Problem issues for ranked table (exclude positive feedback and generic complaint)
    exclude_issues = ("positive_feedback", "not_applicable_positive", "generic_complaint_with_no_detail", "safety_complaints")
    problem_issues = [iss for iss in df_classified["issue"].unique() if iss not in exclude_issues]

    findings = []

    for issue_key in problem_issues:
        sub = df_classified[df_classified["issue"] == issue_key]
        if sub.empty:
            continue

        issue_cnt = len(sub)
        issue_low_cnt = len(sub[sub["score"].isin([1, 2])])
        share_of_all = round(issue_cnt / total_reviews * 100, 1)
        share_of_low = round(issue_low_cnt / total_low * 100, 1) if total_low > 0 else 0.0

        # 30-day trend comparison
        recent_sub = sub[sub["at_dt"] >= t_30d]
        prev_sub = sub[(sub["at_dt"] >= t_60d) & (sub["at_dt"] < t_30d)]
        cnt_recent = len(recent_sub)
        cnt_prev = len(prev_sub)
        if cnt_recent < 5 or cnt_prev < 5:
            is_trend_conclusive = False
            trend_pct_change = None
            trend_display = f"Inconclusive ({cnt_recent} vs {cnt_prev})"
            trend_factor = 1.0
        else:
            is_trend_conclusive = True
            trend_pct_change = round(((cnt_recent - cnt_prev) / cnt_prev * 100), 1)
            sign = "+" if trend_pct_change > 0 else ""
            trend_display = f"{sign}{trend_pct_change}% ({cnt_recent} vs {cnt_prev})"
            trend_factor = 1.2 if cnt_recent > cnt_prev else 1.0

        # Quotes with review IDs
        quotes = []
        if "evidence_quote" in sub.columns:
            for _, r in sub.dropna(subset=["evidence_quote"]).iterrows():
                q_text = str(r["evidence_quote"]).strip()
                if q_text and len(q_text) >= 10:
                    quotes.append({
                        "review_id": r["review_id"],
                        "quote": q_text,
                        "score": int(r["score"]),
                        "date": str(r["at"])[:10]
                    })
                if len(quotes) >= 3:
                    break

        # Dominant responsibility and stage
        if "responsibility" in sub.columns:
            resp_counts = sub["responsibility"].value_counts()
            dom_resp = resp_counts.index[0] if not resp_counts.empty else "unclear"
        else:
            dom_resp = "unclear"

        if "journey_stage" in sub.columns:
            stage_counts = sub["journey_stage"].value_counts()
            dom_stage = stage_counts.index[0] if not stage_counts.empty else "general_app"
        else:
            dom_stage = "general_app"

        avg_severity = float(sub["severity"].mean()) if "severity" in sub.columns else 2.0

        # Star impact scenario
        impact = compute_star_impact_scenario(df, issue_key)

        # Effort estimation heuristics
        if dom_resp == "app_technical" and issue_key in ("login_and_otp", "feature_request_or_usability"):
            effort = "small"
        elif dom_resp == "app_technical" or issue_key in ("tracking_and_eta", "booking_failure_or_wrong_date", "crashes_and_slowness"):
            effort = "medium"
        elif dom_resp in ("operations_fleet", "enterprise_configuration") or issue_key in ("late_pickup_or_vehicle_assignment", "route_planning_and_trip_assignment"):
            effort = "large"
        else:
            effort = "medium"

        effort_score = weights.get("effort_weights", {}).get(effort, 2.0)

        # Score formula (No artificial safety boost here; pure data-driven ranking)
        vol_score = np.log1p(issue_cnt) * weights.get("volume_weight", 1.2)
        sev_score = avg_severity * weights.get("severity_weight", 1.5)
        impact_score = (impact["delta"] * 10.0) * weights.get("star_impact_weight", 2.0)
        
        raw_score = (vol_score * sev_score * trend_factor * max(0.5, impact_score)) / effort_score

        # Add update-related keyword breakdown for crashes
        extra_note = None
        if issue_key == "crashes_and_slowness":
            crash_low_sub = sub[sub["score"].isin([1, 2])]
            if "content" in crash_low_sub.columns:
                crash_kw_cnt = int(crash_low_sub["content"].str.contains(update_pattern, case=False, na=False).sum())
            else:
                crash_kw_cnt = 0
            extra_note = f"Update-related: {crash_kw_cnt} of {issue_low_cnt} low-star reviews ({round(crash_kw_cnt/issue_low_cnt*100, 1)}%) explicitly mention update, version, reinstall, uninstall or logout."

        findings.append({
            "issue_key": issue_key,
            "title": issue_key.replace("_", " ").title(),
            "count": issue_cnt,
            "low_star_count": issue_low_cnt,
            "share_of_all_reviews": share_of_all,
            "share_of_low_star": share_of_low,
            "recent_30d_count": cnt_recent,
            "prev_30d_count": cnt_prev,
            "is_trend_conclusive": is_trend_conclusive,
            "trend_change_pct": trend_pct_change,
            "trend_display": trend_display,
            "quotes": quotes,
            "dominant_responsibility": dom_resp,
            "dominant_journey_stage": dom_stage,
            "avg_severity": round(avg_severity, 2),
            "is_safety": False,
            "star_impact": impact,
            "estimated_effort": effort,
            "ranking_score": round(raw_score, 1),
            "extra_note": extra_note
        })

    # Sort by ranking score descending (Safety is excluded from score table and presented as separate escalation)
    findings = sorted(findings, key=lambda x: x["ranking_score"], reverse=True)

    # Specific actionable engineering specifications
    specs = generate_engineering_specs()

    return {
        "coverage": {
            "total_reviews": total_reviews,
            "total_low_star": total_low,
            "classified_low_star": classified_low,
            "low_star_coverage_pct": low_coverage,
            "is_provisional": is_provisional
        },
        "safety_escalation": safety_escalation,
        "measurement_gap": measurement_gap,
        "ranked_problems": findings,
        "rank_score_note": "Rank scores within a few points are effectively tied.",
        "engineering_specs": specs,
        "cheap_levers": evaluate_cheap_levers(df)
    }

def generate_engineering_specs() -> list[dict]:
    """Generates the standardized MIS-001 through MIS-009 engineering and operations sprint items."""
    return [
        {
            "key": "MIS-001",
            "title": "SOS reachable in one tap, no blocking pop-ups on the trip screen (safety escalation)",
            "owner": "Android lead",
            "effort": "Small",
            "priority": "Highest",
            "component": "app_technical",
            "issue_key": "safety_complaints",
            "affected_flow": "Active Trip screen and Emergency SOS trigger",
            "affected_versions": "Unversioned / general (e.g. review b1814d48-3e54-4903-a109-e09e05bc3145)",
            "concrete_quotes": [
                "[b1814d48-3e54-4903-a109-e09e05bc3145] 'If someone needs to use SOS button, he/she can not use in timely manner due to useless notification pop ups'"
            ],
            "hypotheses": [
                "App dialog manager renders non-dismissible modal notifications over the active trip view, overlaying and blocking the touch target of the SOS floating action button.",
                "Notification stack fails to respect emergency view hierarchy z-indexing during ride state transitions."
            ],
            "proposed_change": "Enforce top-level z-index window for SOS button that bypasses any in-app notification overlays. Implement persistent 1-tap SOS in system notification bar during active rides.",
            "acceptance_criteria": "1. SOS button is tap-responsive within 500ms under any active modal or notification state.\n2. In-app popups cannot obscure the emergency action container.\n3. Verified in automated Espresso UI tests.",
            "instrumentation_events": "trip_sos_tap, trip_sos_rendered, notification_popup_displayed",
            "internal_data_needed": "Client-side SOS latency logs and modal dismissal telemetry on active trip screen.",
            "first_14_days": "Days 1–3: Inspect WindowManager and DialogFragment hierarchy on trip activity. Days 4–8: Refactor SOS to persistent non-blocking overlay. Days 9–14: Test on multiple Android OEM overlays and ship hotfix.",
            "what_to_measure": "Zero blocked SOS events; 100% successful trigger within 1 tap under stress testing."
        },
        {
            "key": "MIS-002",
            "title": "Fix app not opening or getting stuck after updates; reproduce upgrade path; staged rollout gate",
            "owner": "Android lead + QA",
            "effort": "Medium",
            "priority": "High",
            "component": "app_technical",
            "issue_key": "crashes_and_slowness",
            "affected_flow": "App Cold Launch & Post-Upgrade SQLite/SharedPrefs Migration",
            "affected_versions": "12.19.0 (10 low-star), 12.17.0 (8 low-star), 12.18.1 (5 low-star), 12.14.0 (3.37★ average)",
            "concrete_quotes": [
                "[60798e45-939e-4a99-8f5b-17383a891db6] 'whenever i update this app, i am not able to open the app again, I need to uninstall and reinstall again.'",
                "[7781ccc3-e390-49cb-b574-fb3213c2e74a] 'application not working with pixel 8 android version 17... installed and uninstalled...still not working...open and close automatically'",
                "[e735e280-9992-470e-b8df-d9b4a0e1e214] 'Unable to open the app on my phone. closes as soon as I try to open'"
            ],
            "hypotheses": [
                "Room/SQLite schema migration failure on upgrade causes unhandled SQLiteConstraintException or IllegalStateException during Application.onCreate().",
                "Cached authentication tokens or Room database corrupted on delta APK upgrade, forcing users to uninstall and reinstall to wipe app data.",
                "Android 14/15/16 background initialization changes causing ANR on modern Pixel/OnePlus devices."
            ],
            "proposed_change": "Wrap local database upgrade migrations with automated fallback recovery (repair cache rather than crash). Set up CI upgrade tests (v12.14 -> v12.18 -> v12.19). Enforce staged rollout gates (freeze if crash-free sessions drop below 99.5%).",
            "acceptance_criteria": "1. 100% of schema migration test matrices pass in automated CI across 5 prior versions.\n2. Crash-free user rate >= 99.5% on canary 5% rollout.\n3. Automatic database corruption recovery clears bad cache without crashing.",
            "instrumentation_events": "app_launch_start, db_migration_success, db_migration_failure, app_cold_start_completed",
            "internal_data_needed": "Crashlytics / Firebase stack traces grouped by app_version and Android OS for launch crashes.",
            "first_14_days": "Days 1–4: Reproduce upgrade path in QA emulator matrix; analyze Crashlytics launch exceptions. Days 5–9: Fix Room schema migration and corrupted state handler. Days 10–14: Staged rollout (5% -> 20% -> 100%) with automated ANR/crash halt.",
            "what_to_measure": "Crash-free user rate (target: >= 99.5%); reduction in update-related review complaints."
        },
        {
            "key": "MIS-003",
            "title": "Fix logout loop and OTP delivery; add resend and a 'your company has not added you' message",
            "owner": "Backend/auth lead",
            "effort": "Small",
            "priority": "High",
            "component": "app_technical",
            "issue_key": "login_and_otp",
            "affected_flow": "Authentication, Session Renewal, and Employee Account Onboarding",
            "affected_versions": "12.17.0 (6 low-star), 12.19.0 (2 low-star), 11.5.21 (1 low-star)",
            "concrete_quotes": [
                "[72e74b90-1da1-49cc-87c0-6bc42af65ba3] 'Pathetic . it logs out every time.'",
                "[c9c2d1f3-da5a-457f-b3cd-479afddacd8a] 'I\\'m not able to login as it was automatically logged out and no otp received with registered mobile number'",
                "[d6cbf0b5-c7e3-4474-8a61-6a65d98ba8cf] 'Unable to login in the App. Both Mobile Otp and Email OTP options are not working'",
                "[d0013885-22ce-4c15-b188-eb1b58d912d3] 'doesn\\'t send OTP, email, txt, WhatsApp no otps.'"
            ],
            "hypotheses": [
                "Session refresh token expires prematurely or encounters 401 on background sync, causing silent logout back to welcome screen.",
                "SMS gateway carrier routing failures or DND throttling drop OTP delivery without client fallback.",
                "Unregistered enterprise employees attempt login before their corporate HR roster has imported their phone number, resulting in generic 'OTP failed' instead of clear explanation."
            ],
            "proposed_change": "Graceful session refresh with silent token renewal. Add multi-channel OTP resend (SMS, WhatsApp, Email). If user number is not in enterprise roster, display explicit guidance: 'Your mobile number is not yet registered by your company HR transport team'.",
            "acceptance_criteria": "1. Multi-channel OTP fallback button appears within 30s.\n2. Clear error banner for unrostered numbers explaining HR dependency.\n3. Session token auto-renews without logging user out during active shifts.",
            "instrumentation_events": "auth_otp_requested, auth_otp_delivered, auth_otp_failed, auth_session_expired, auth_unregistered_employee",
            "internal_data_needed": "SMS vendor delivery receipt logs, telecom failure codes, enterprise HR roster sync audit tables.",
            "first_14_days": "Days 1–3: Inspect auth service token TTL and 401 interception logic. Days 4–8: Implement WhatsApp/Email OTP fallback and explicit unrostered error messaging. Days 9–14: QA test and deploy to production auth service.",
            "what_to_measure": "First-attempt login success rate (proposed target; baseline unknown); drop in OTP-related 1-star reviews."
        },
        {
            "key": "MIS-004",
            "title": "One-tap boarding OTP; stop repeated rating prompts after every ride (verify in-app vs Play prompt)",
            "owner": "Product + Android",
            "effort": "Small",
            "priority": "High",
            "component": "app_technical",
            "issue_key": "feature_request_or_usability",
            "affected_flow": "Cab Boarding Verification and Post-Trip Completion",
            "affected_versions": "12.19.0 (review 3d87f169 and f9fce9fe), 12.18.1 (c4c982a7), 12.17.0 (714eb4f9)",
            "concrete_quotes": [
                "[3d87f169-2508-4a07-9e5a-d63b2c548ed3] 'The new feature and very annoying feature which you have introduced - when you click view otp , it pops up the seat belt safely first. Why do you ask for user input one more click . very annoying I should be able to see the otp in one click.'",
                "[f9fce9fe-8115-4a30-8d09-d8bdac76837d] 'forcing me to give rating after every ride, so I came here to give you 1 star. because if I don\\'t rate it\\'s not allowing me to use the app'",
                "[c4c982a7-763c-4e2b-889a-17109a961dc7] 'why the hell no option of skip rating.if I don\\'t want rate.'",
                "[714eb4f9-7828-4af2-a2a8-0d690feffa59] 'always keeps asking for rating'"
            ],
            "hypotheses": [
                "Extra safety modal popup (seat belt acknowledgement) was placed before OTP display, adding friction during boarding under rain or hurry.",
                "Trip rating modal blocks subsequent app usage with no 'Skip' option, causing commuters to retaliate on the Play Store. (Note: ambiguous whether in-app trip rating or Play Store prompt; verify in app implementation)."
            ],
            "proposed_change": "Display boarding OTP immediately in 1 tap on the main card; make seat belt confirmation non-blocking or inline. Add a clear 'Skip' button to in-app ride ratings; never block app booking or navigation for feedback.",
            "acceptance_criteria": "1. Boarding OTP is visible within 1 tap from active trip card.\n2. In-app trip rating dialog has a dismissible 'Skip' button and never blocks app navigation.\n3. Verify whether complaints reference in-app trip rating or Play prompt.",
            "instrumentation_events": "trip_otp_view_clicked, trip_rating_modal_shown, trip_rating_skipped",
            "internal_data_needed": "Client-side rating modal impression vs skip conversion analytics.",
            "first_14_days": "Days 1–3: Remove blocking modal on OTP view. Days 4–7: Add dismiss button to post-trip rating. Days 8–14: Release in v12.20.0.",
            "what_to_measure": "Reduction in prompt-frustration 1-star reviews; boarding OTP view latency."
        },
        {
            "key": "MIS-005",
            "title": "Reply to 1-2 star reviews within 24h, human-approved, never automatic",
            "owner": "Support lead",
            "effort": "Small",
            "priority": "High",
            "component": "operations_fleet",
            "issue_key": "support_and_response",
            "affected_flow": "Google Play Console Developer Response Workflow",
            "affected_versions": "All versions",
            "concrete_quotes": [
                "[f5890267-a88c-4c91-a588-439ca31ef0bf] 'most terible service no customer support and no safety'",
                "[ab22d06f-a3be-49e3-a460-5ef157ec534c] 'worst app . zero support. unsafe for female'"
            ],
            "hypotheses": [
                "Lack of Play Console integration into customer support ticketing system leads to 0.71% reply rate (only 3 of 422 low-star reviews received developer responses).",
                "Unacknowledged commuters assume company does not care about reported commute failures."
            ],
            "proposed_change": "Connect Play Console API to support ticketing (Zendesk/Freshdesk). Institute a human-in-the-loop 24-hour response SLA on all 1–2★ reviews. Replies must be human-approved with specific ticket IDs, never canned automated bots.",
            "acceptance_criteria": "1. Low-star developer reply rate raised from 0.7% to > 90% (proposed target; baseline unknown).\n2. Median response latency < 24 hours.\n3. No automated bot replies posted.",
            "instrumentation_events": "play_console_review_ingested, support_ticket_created, developer_reply_published",
            "internal_data_needed": "Play Console API service account credentials, support team shift schedules.",
            "first_14_days": "Days 1–4: Integrate Play Console review webhooks into support queue. Days 5–8: Define human response templates and escalation playbooks. Days 9–14: Train team and launch 24h SLA.",
            "what_to_measure": "Developer reply rate on 1–2★ reviews; updated review star lift."
        },
        {
            "key": "MIS-006",
            "title": "Tracking/ETA reliability and delay alerts",
            "owner": "Tracking backend + Android",
            "effort": "Medium",
            "priority": "Medium",
            "component": "app_technical",
            "issue_key": "tracking_and_eta",
            "affected_flow": "Real-time Vehicle Tracking and Live Map View",
            "affected_versions": "12.19.0, 12.18.1, 12.17.0 (36 low-star reviews total)",
            "concrete_quotes": [
                "[7a6441a0-2383-4dd7-83f7-8d54c4af8111] 'damned!! worst app. Can\\'t do live tracking or live boarding activities. suddenly it shows up at your location'",
                "[edd96d77-83f2-4a31-9a5e-b11c25b727a3] 'Daily showing wrong routes and High travel time. Not safety for employees.'"
            ],
            "hypotheses": [
                "Driver app background location throttle causes jumpy cab icons and sudden arrivals.",
                "ETA calculation lacks real-time traffic delay push alerts when cab is delayed."
            ],
            "proposed_change": "Upgrade driver app location foreground service; add client dead-reckoning; push delay alerts if ETA slips by > 5 minutes.",
            "acceptance_criteria": "1. Vehicle location update interval <= 10s during active trips.\n2. Proactive push notification sent within 60s if vehicle is delayed >= 5m.\n3. Smooth map interpolation instead of teleports.",
            "instrumentation_events": "driver_gps_ping, trip_eta_calculated, trip_delay_push_sent",
            "internal_data_needed": "Driver GPS ping interval distributions and vehicle telematics.",
            "first_14_days": "Days 1–5: Measure driver GPS dropouts. Days 6–10: Add push delay notification service. Days 11–14: Beta test on selected fleet routes.",
            "what_to_measure": "ETA Mean Absolute Error; reduction in tracking-related 1-star reviews."
        },
        {
            "key": "MIS-007",
            "title": "Booking failure/wrong date: clearer error reasons",
            "owner": "Booking service owner",
            "effort": "Medium",
            "priority": "Medium",
            "component": "app_technical",
            "issue_key": "booking_failure_or_wrong_date",
            "affected_flow": "Shift Commute Roster Selection and Booking Confirmation",
            "affected_versions": "12.19.0, 12.17.0, 12.14.0 (26 low-star reviews total)",
            "concrete_quotes": [
                "[823b9c8b-afde-47e7-abad-fb60f14ea562] 'app stuck all the time unable to schedule pathetic'",
                "[9a43eec8-6435-4987-84c5-58792ddbeeb4] 'my cab not scheduled from company side but trainer want to approve a cab transport team not giving any solution'"
            ],
            "hypotheses": [
                "Enterprise corporate cutoff policy (e.g. 4-hour advance booking limit) triggers generic failure toasts rather than actionable explanations.",
                "Shift date boundaries cause timezone mismatch during midnight shift scheduling."
            ],
            "proposed_change": "Display company transport cutoff rules clearly on schedule card. Replace generic failures with exact explanations ('Booking closed at 17:00 as per company policy').",
            "acceptance_criteria": "1. 100% of booking error messages state explicit policy or technical reason.\n2. Inline indicator shows cutoff deadline for upcoming shifts.\n3. Client-side retry queue on flaky mobile connections.",
            "instrumentation_events": "booking_attempt, booking_success, booking_failed_policy_cutoff, booking_failed_network",
            "internal_data_needed": "Booking API HTTP 4xx/5xx failure error code distributions.",
            "first_14_days": "Days 1–4: Audit top booking failure codes. Days 5–9: Deploy user-facing error message mapping. Days 10–14: Ship updated booking modal.",
            "what_to_measure": "Booking success conversion rate (proposed target; baseline unknown); booking complaints in reviews."
        },
        {
            "key": "MIS-008",
            "title": "One-tap 'what went wrong?' reason picker at trip end",
            "owner": "Product manager",
            "effort": "Small",
            "priority": "Medium",
            "component": "product_ux",
            "issue_key": "generic_complaint_with_no_detail",
            "affected_flow": "Trip Completion and Post-Commute Feedback",
            "affected_versions": "All versions (addresses 110 low-star reviews with no detail)",
            "concrete_quotes": [
                "[Generic complaints: 'worst app', 'pathetic', 'bad', 'waste']"
            ],
            "hypotheses": [
                "Users venting with single-word 1-star reviews provide zero diagnostic signal for engineering to act on.",
                "Commuters lack a frictionless 1-tap categorization mechanism inside the app when things go wrong."
            ],
            "proposed_change": "Introduce a 1-tap post-trip diagnostic picker ('Cab Late', 'App Glitch', 'Driver Issue', 'Routing') at trip completion. Keep Play Store option visible; never suppress or incentivize ratings.",
            "acceptance_criteria": "1. Reason chips visible upon selecting 1–3 stars on trip end.\n2. One tap captures issue category without requiring text typing.\n3. No gating or blocking of Play Store rating.",
            "instrumentation_events": "trip_feedback_reason_selected, trip_feedback_submitted",
            "internal_data_needed": "Post-trip feedback completion rate and reason chip click distribution.",
            "first_14_days": "Days 1–4: Design 1-tap reason chips. Days 5–9: Implement client feedback screen. Days 10–14: Roll out to pilot accounts.",
            "what_to_measure": "Share of low-star reviews with actionable reasons (aiming to reduce no-reason reviews from 26.1%)."
        },
        {
            "key": "MIS-009",
            "title": "Route planning, late pickup and driver behaviour: pass evidence to transport operations (not an app fix)",
            "owner": "Operations lead",
            "effort": "Large",
            "priority": "Medium",
            "component": "operations_fleet",
            "issue_key": "operations_transport_bundle",
            "affected_flow": "Fleet Routing, Vendor Driver Onboarding, and Shift Dispatch SLA",
            "affected_versions": "All versions (53 low-star reviews across route planning, driver behavior, late pickup)",
            "concrete_quotes": [
                "[f5890267-a88c-4c91-a588-439ca31ef0bf] 'worst cab providers no credebility and worst drivers onboarded'",
                "[72b21544-5b6e-4ae8-b33e-1c641857b98f] 'No concern for female employees at logout time, they won\\'t even call the employee at late night logout before making no show.'",
                "[edd96d77-83f2-4a31-9a5e-b11c25b727a3] 'Daily showing wrong routes and High travel time.'"
            ],
            "hypotheses": [
                "Inefficient multi-stop employee clustering generates excessive ride times (60+ minutes for 15km commutes).",
                "Vendor cab drivers mark early no-shows without attempting phone calls to avoid waiting times."
            ],
            "proposed_change": "Export weekly review evidence dossiers to vendor fleet operations teams; enforce vendor SLA penalties for unattempted no-shows; audit dispatch route clustering algorithms.",
            "acceptance_criteria": "1. Weekly review feedback dossier automatically delivered to vendor fleet operations leads.\n2. Mandatory driver phone attempt logged before driver app allows 'No-Show' trigger.\n3. Route circuity index capped at 1.4x direct distance.",
            "instrumentation_events": "driver_call_attempted, no_show_triggered, route_planned_vs_actual_distance",
            "internal_data_needed": "Vendor fleet driver penalty logs, GPS track vs scheduled route variance, call log telematics.",
            "first_14_days": "Days 1–5: Compile fleet vendor feedback report. Days 6–10: Enforce call verification on driver app no-show. Days 11–14: Review route optimization clustering parameters.",
            "what_to_measure": "Driver-related complaints in reviews; route circuity ratio; vendor SLA breach rates."
        }
    ]

def evaluate_cheap_levers(df: pd.DataFrame) -> dict:
    """Evaluates low-hanging growth and reputation levers."""
    total_reviews = len(df)
    low_reviews = df[df["score"].isin([1, 2])]
    if "reply_content" in low_reviews.columns:
        replied_low = low_reviews[low_reviews["reply_content"].notna() & (low_reviews["reply_content"].str.strip() != "")]
        reply_rate = round(len(replied_low) / len(low_reviews) * 100, 1) if len(low_reviews) > 0 else 0.0
    else:
        reply_rate = 0.0

    return {
        "in_app_review_prompt": {
            "title": "Google In-App Review API Integration",
            "current_state": "Reviews are largely unprompted or prompted at friction points (e.g. ambiguous review complaint: 'forcing me to give rating after every ride'—needs verification whether in-app trip rating or Play prompt).",
            "recommendation": (
                "Trigger Google Play In-App Review API strictly after a high-satisfaction milestone: e.g., "
                "after 3 consecutive on-time trips completed without delay or dispute. Never prompt immediately "
                "after a delayed cab, cancelled booking, or app crash. Include an accessible in-app 'Report a Problem' "
                "button directly routing to the internal transport desk to intercept complaints before they reach the Play Store. "
                "Nothing is posted or changed automatically."
            ),
            "guardrails": "Strict adherence to Google Play policies: no gating, no monetary incentives, no suppression, zero automated reviews."
        },
        "developer_replies": {
            "title": "Human-in-the-Loop Developer Review Response SLA",
            "current_state": f"Current reply rate on 1-2 star reviews is only {reply_rate}%. Users feel abandoned.",
            "recommendation": (
                "Establish a dedicated 24-hour response SLA for all 1-2 star reviews. Every reply must be approved "
                "by a human operations lead (never automated canned bot responses). Acknowledge specific pain "
                "(e.g., 'We apologize for the delayed cab on your night shift'), provide a direct transport ticket ID, "
                "and invite them to update their rating once resolved. Nothing is posted automatically."
            )
        },
        "staged_rollouts": {
            "title": "Staged Rollout & Crash-Rate Gating",
            "current_state": "Version analysis revealed sharp rating drops on specific versions (e.g., v12.14.0 lowest observed at 3.37★).",
            "recommendation": (
                "Adopt strict phased rollout gates: 5% day 1, 15% day 3, 50% day 5, 100% day 7. Freeze rollout "
                "immediately if crash-free user rate drops below 99.5% or Play Console ANR rate exceeds 0.47%."
            )
        }
    }

def export_action_items_csv(specs: list[dict], output_path=None) -> str:
    """Exports engineering recommendations as a Jira/Linear compatible CSV matching MIS-001..MIS-009."""
    if output_path is None:
        output_path = ACTION_ITEMS_PATH

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for s in specs:
        rows.append({
            "Issue Key": s["key"],
            "Summary": s["title"],
            "Issue Type": "Story" if s["effort"] != "Small" else "Task",
            "Priority": s["priority"],
            "Component": s["component"],
            "Estimated Effort": s["effort"],
            "Owner": s["owner"],
            "Description": f"Affected Flow: {s.get('affected_flow', '')}\n\nHypotheses:\n" + "\n".join(s.get("hypotheses", [])) + f"\n\nProposed Change:\n{s.get('proposed_change', '')}\n\nFirst 14 Days:\n{s.get('first_14_days', '')}",
            "Acceptance Criteria": s.get("acceptance_criteria", ""),
            "Metrics to Measure": s.get("what_to_measure", ""),
            "Status": "Proposed"
        })

    df_out = pd.DataFrame(rows)
    df_out.to_csv(output_path, index=False, encoding="utf-8")
    return str(output_path)
