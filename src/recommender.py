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

    # Filter only problem issues (exclude pure positive feedback)
    df_classified = df[df["is_classified"] == 1].copy()
    problem_issues = [iss for iss in df_classified["issue"].unique() if iss not in ("positive_feedback", "not_applicable_positive")]

    findings = []

    for issue_key in problem_issues:
        sub = df_classified[df_classified["issue"] == issue_key]
        if sub.empty:
            continue

        issue_cnt = len(sub)
        issue_low_cnt = len(sub[sub["score"].isin([1, 2])])
        share_of_all = round(issue_cnt / total_reviews * 100, 2)
        share_of_low = round(issue_low_cnt / total_low * 100, 2) if total_low > 0 else 0.0

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
        is_safety = (issue_key == "safety_complaints")

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

        # Score formula
        vol_score = np.log1p(issue_cnt) * weights.get("volume_weight", 1.2)
        sev_score = avg_severity * weights.get("severity_weight", 1.5)
        impact_score = (impact["delta"] * 10.0) * weights.get("star_impact_weight", 2.0)
        
        raw_score = (vol_score * sev_score * trend_factor * max(0.5, impact_score)) / effort_score
        if is_safety:
            raw_score += weights.get("safety_escalation_boost", 100.0)

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
            "is_safety": is_safety,
            "star_impact": impact,
            "estimated_effort": effort,
            "ranking_score": round(raw_score, 2)
        })

    # Sort by ranking score descending
    findings = sorted(findings, key=lambda x: x["ranking_score"], reverse=True)

    # Attach engineered specs to Top 3
    specs = generate_engineering_specs(findings[:5])

    return {
        "coverage": {
            "total_reviews": total_reviews,
            "total_low_star": total_low,
            "classified_low_star": classified_low,
            "low_star_coverage_pct": low_coverage,
            "is_provisional": is_provisional
        },
        "ranked_problems": findings,
        "engineering_specs": specs,
        "cheap_levers": evaluate_cheap_levers(df)
    }

def generate_engineering_specs(top_findings: list[dict]) -> list[dict]:
    """Generates ready-to-execute engineering specifications for the top problems."""
    specs = []
    
    spec_templates = {
        "late_pickup_or_vehicle_assignment": {
            "hypothesis": "Hypothesis: Fleet dispatch algorithms assign cabs too close to shift start times without real-time traffic buffers, combined with driver absenteeism or late depot departure.",
            "other_explanations": "Alternative explanations: Corporate security check delays at pickup points, or employee-reported delay during driver route re-sequencing.",
            "proposed_change": "Introduce proactive delay alerts: If vehicle is delayed by > 5 mins, trigger push notification with revised ETA and 1-tap call/escalate button. Provide driver standby buffer in dispatch logic.",
            "owner": "Mobile Tech Lead + Fleet Operations PM",
            "internal_data_needed": "Cab telematics vs dispatch timestamps, buffer SLA breach rates by fleet vendor, driver no-show rates.",
            "acceptance_criteria": "1. Push notification sent within 60s when cab ETA exceeds scheduled pickup by >= 5m.\n2. In-app tracking shows accurate delay reason banner.\n3. Escalation button connects directly to transport desk helpline.",
            "edge_cases": "Cab GPS lost in cellular dead zone (graceful fallback to last known location + warning); employee changes pickup pin last minute.",
            "what_to_measure": "Play Store lateness complaint share (target: -30%), call volume to transport desk, driver delay notification open rate.",
            "first_14_days": "Days 1-4: Audit dispatch-to-pickup telemetry for worst 10 corporate accounts. Days 5-9: Implement client-side push notification on ETA slip. Days 10-14: Test in staging and ship to 10% beta fleet."
        },
        "tracking_and_eta": {
            "hypothesis": "Hypothesis: ETA engine relies on static distance matrices or outdated speed profiles rather than live Google Maps/traffic telemetry, causing wild swings in arrival estimates.",
            "other_explanations": "Alternative explanations: Driver mobile devices aggressively throttle background GPS to save battery; driver app location permissions set to 'Only while in use'.",
            "proposed_change": "Upgrade driver app location cadence to high-accuracy background polling during active trips; integrate real-time traffic-adjusted routing API; add client-side dead reckoning.",
            "owner": "Mobile Platform Team + Routing Engine Lead",
            "internal_data_needed": "Driver GPS ping interval distributions, ETA variance vs actual arrival timestamps in ride history.",
            "acceptance_criteria": "1. GPS ping interval maintained at <= 10s during active ride.\n2. ETA calculation re-anchors to live traffic every 60s.\n3. Map renders smooth interpolation instead of jumping pins.",
            "edge_cases": "Driver phone enters extreme battery-saver mode (prompt driver with audible foreground alert to plug into charger); tunnel / underground parking loss of fix.",
            "what_to_measure": "ETA Mean Absolute Error (MAE) reduced from > 8 min to < 3 min; tracking-related low-star reviews drop by 50%.",
            "first_14_days": "Days 1-3: Measure driver GPS ping dropout rate in production telemetry. Days 4-8: Update driver background service to Android foreground service with persistent notification. Days 9-14: A/B test live traffic ETA pipeline."
        },
        "booking_failure_or_wrong_date": {
            "hypothesis": "Hypothesis: Roster synchronization between enterprise HRMS and MoveInSync database fails silently or has timezone/cutoff misalignments, rejecting valid booking requests.",
            "other_explanations": "Alternative explanations: Enterprise transport policy cutoffs (e.g., 3-hour advance booking limit) are poorly communicated in the UI, leading users to believe the app failed.",
            "proposed_change": "Revamp booking UX: Explicitly display company cutoff rules inline, show clear error states with actionable reasons ('Booking closed by company transport policy at 17:00' instead of 'Failed to book'), and add offline retry queue.",
            "owner": "Employee App PM + Enterprise Integration Lead",
            "internal_data_needed": "Booking API HTTP 4xx/5xx error breakdown, client-side booking funnel dropoff analytics, roster sync lag metrics.",
            "acceptance_criteria": "1. Inline countdown to booking cutoff visible on shift selector screen.\n2. Detailed human-readable error reasons returned for all failed bookings.\n3. Client-side caching preserves user inputs on intermittent network failure.",
            "edge_cases": "Employee shift changed in HRMS while booking is in flight; midnight shift crossing calendar day boundary.",
            "what_to_measure": "Booking success conversion rate (target: > 98.5%), booking error complaints in reviews (target: -60%).",
            "first_14_days": "Days 1-4: Classify top 5 error codes returned by booking endpoint. Days 5-9: Replace generic error toasts with actionable modal dialogs. Days 10-14: Roll out to pilot enterprise account."
        },
        "login_and_otp": {
            "hypothesis": "Hypothesis: SMS gateway throttling or corporate email spam filters cause delayed OTP delivery exceeding the 60-second in-app timeout, locking out employees before shifts.",
            "other_explanations": "Alternative explanations: Employee device SMS permission denied, or company single-sign-on (SSO) SAML token expiry during shift changes.",
            "proposed_change": "Introduce multi-channel fallback: WhatsApp OTP and corporate email OTP backup if SMS is not received in 30 seconds; implement auto-reading OTP via SMS Retriever API.",
            "owner": "Authentication & Security Lead",
            "internal_data_needed": "SMS OTP delivery latency distributions by telecom carrier, OTP resend request rate, SSO session termination logs.",
            "acceptance_criteria": "1. Multi-channel OTP option (WhatsApp / Email) appears automatically after 30s.\n2. SMS Retriever API auto-populates OTP without manual copy-paste.\n3. Clear troubleshooting guide linked directly on login screen.",
            "edge_cases": "Employee roaming with international SIM; telecom DND (Do Not Disturb) blocking transactional SMS.",
            "what_to_measure": "Login success rate on first attempt (target: > 95%), login complaint share in reviews (target: -75%).",
            "first_14_days": "Days 1-3: Review SMS provider delivery SLAs and failure codes. Days 4-8: Integrate WhatsApp Business OTP fallback endpoint. Days 9-14: Deploy client-side SMS retriever integration."
        },
        "safety_complaints": {
            "hypothesis": "Hypothesis: Night-time cab drops or female employee commutes encounter unverified driver substitutions, escort guard absenteeism, or SOS button unresponsive states.",
            "other_explanations": "Alternative explanations: Driver arguments over drop location outside gated societies causing feeling of unsafe environment.",
            "proposed_change": "Zero-tolerance safety workflow: Enforce driver facial verification before trip start, mandatory OTP verification before car rolls, 1-tap SOS that immediately rings transport security room, and auto-call female employees after drop.",
            "owner": "Head of Safety & Compliance + Mobile Security Lead",
            "internal_data_needed": "SOS button tap history, driver identity mismatch incident reports, escort security compliance audits.",
            "acceptance_criteria": "1. Driver selfie match required every 12 hours or before shift.\n2. SOS button in persistent notification bar accessible even on lock screen.\n3. Drop confirmation auto-call triggers for female night shifts.",
            "edge_cases": "Low battery on employee device during night commute; network disconnection during active SOS.",
            "what_to_measure": "SOS response SLA (< 30 seconds), zero unresolved safety escalations.",
            "first_14_days": "Immediate Day 1: Audit all reviews flagged with safety. Days 2-5: Review 24/7 security control room call routing. Days 6-14: Implement persistent lock-screen SOS widget."
        }
    }

    for f in top_findings:
        key = f["issue_key"]
        template = spec_templates.get(key, {
            "hypothesis": f"Hypothesis: Systemic friction in {f['title']} driven by lack of feedback loops.",
            "other_explanations": "Alternative explanations: Edge case device incompatibility or operational variance.",
            "proposed_change": f"Refactor user journey for {f['title']} with clear UX feedback and robust backend retry.",
            "owner": f"{f['dominant_responsibility'].replace('_', ' ').title()} Lead",
            "internal_data_needed": "Crash logs, server telemetry, and user feedback logs.",
            "acceptance_criteria": f"Resolve root cause of {f['title']} complaints with verifiable regression tests.",
            "edge_cases": "Network timeouts, device low memory.",
            "what_to_measure": f"Reduction in {f['title']} complaints.",
            "first_14_days": "Audit telemetry, formulate test fix, and roll out canary release."
        })

        specs.append({
            "issue_key": key,
            "title": f["title"],
            "count": f["count"],
            "share_of_low_star": f["share_of_low_star"],
            "star_impact_scenario": f["star_impact"]["delta"],
            "estimated_effort": f["estimated_effort"],
            "dominant_responsibility": f["dominant_responsibility"],
            **template
        })

    return specs

def evaluate_cheap_levers(df: pd.DataFrame) -> dict:
    """Evaluates low-hanging growth and reputation levers."""
    total_reviews = len(df)
    low_reviews = df[df["score"].isin([1, 2])]
    if "reply_content" in low_reviews.columns:
        replied_low = low_reviews[low_reviews["reply_content"].notna() & (low_reviews["reply_content"].str.strip() != "")]
        reply_rate = round(len(replied_low) / len(low_reviews) * 100, 2) if len(low_reviews) > 0 else 0.0
    else:
        reply_rate = 0.0

    return {
        "in_app_review_prompt": {
            "title": "Google In-App Review API Integration",
            "current_state": "Reviews are largely unprompted or prompted at friction points (e.g. user review complaint: 'forcing me to give rating after every ride').",
            "recommendation": (
                "Trigger Google Play In-App Review API strictly after a high-satisfaction milestone: e.g., "
                "after 3 consecutive on-time trips completed without delay or dispute. Never prompt immediately "
                "after a delayed cab, cancelled booking, or app crash. Include an accessible in-app 'Report a Problem' "
                "button directly routing to the internal transport desk to intercept complaints before they reach the Play Store."
            ),
            "guardrails": "Strict adherence to Google Play policies: no gating, no monetary incentives, no suppression."
        },
        "developer_replies": {
            "title": "Human-in-the-Loop Developer Review Response SLA",
            "current_state": f"Current reply rate on 1-2 star reviews is only {reply_rate}%. Users feel abandoned.",
            "recommendation": (
                "Establish a dedicated 24-hour response SLA for all 1-2 star reviews. Every reply must be approved "
                "by a human operations lead (never automated canned bot responses). Acknowledge specific pain "
                "(e.g., 'We apologize for the delayed cab on your night shift'), provide a direct transport ticket ID, "
                "and invite them to update their rating once resolved."
            )
        },
        "staged_rollouts": {
            "title": "Staged Rollout & Crash-Rate Gating",
            "current_state": "Version analysis revealed sharp rating drops on specific versions (e.g., v12.14.0 dropped to 3.37★).",
            "recommendation": (
                "Adopt strict phased rollout gates: 5% day 1, 15% day 3, 50% day 5, 100% day 7. Freeze rollout "
                "immediately if crash-free user rate drops below 99.5% or Play Console ANR (App Not Responding) rate exceeds 0.47%."
            )
        }
    }

def export_action_items_csv(specs: list[dict], output_path=None) -> str:
    """Exports engineering recommendations as a Jira/Linear compatible CSV."""
    if output_path is None:
        output_path = ACTION_ITEMS_PATH

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for idx, s in enumerate(specs, start=1):
        rows.append({
            "Issue Key": f"MIS-{idx:03d}",
            "Summary": f"Fix {s['title']} ({s['dominant_responsibility']})",
            "Issue Type": "Story" if s["estimated_effort"] != "small" else "Task",
            "Priority": "Highest" if idx == 1 or "safety" in s["issue_key"] else ("High" if idx <= 3 else "Medium"),
            "Component": s["dominant_responsibility"],
            "Estimated Effort": s["estimated_effort"].capitalize(),
            "Owner": s["owner"],
            "Description": f"{s['hypothesis']}\n\nProposed Change:\n{s['proposed_change']}\n\nFirst 14 Days:\n{s['first_14_days']}",
            "Acceptance Criteria": s["acceptance_criteria"],
            "Metrics to Measure": s["what_to_measure"],
            "Status": "Proposed"
        })

    df_out = pd.DataFrame(rows)
    df_out.to_csv(output_path, index=False, encoding="utf-8")
    return str(output_path)
