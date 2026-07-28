"""Red-flag triage rules and in-app guidance (A3 severity routing).

Structured intake per category → severity → guidance. Positives fan out to
app.signal_event (timeline) and app.queue_item (provider alert) in
routers/redflag.py.

This is **routing and education, not diagnosis** — see core-functionality.md §E
and security-foundations.md §5. Guidance text tells the patient who to contact
and how fast; it never names a condition as fact.

Severity vocabulary matches the existing signal_event / queue_item columns:
red | yellow | green. Queue priority follows the seeded demo convention in
db/seed_queue_demo.py, where LOWER sorts first (ORDER BY COALESCE(priority,999)).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Queue priority by severity — red app symptoms sort above the seeded
# readmit/PCP items (which use 10–45).
QUEUE_PRIORITY = {"red": 5, "yellow": 25}

GUIDANCE: Dict[str, Dict[str, str]] = {
    "call_911": {
        "headline": "Call 911 now",
        "body": (
            "These symptoms can be an emergency. Call 911 or have someone take "
            "you to the nearest emergency department right away. Do not drive "
            "yourself. Your care team at Memorial General will be notified."
        ),
        "urgency": "emergency",
    },
    "go_to_ed": {
        "headline": "Go to the emergency department today",
        "body": (
            "This needs to be checked in person today. Go to the emergency "
            "department, or call 911 if you feel worse on the way. Your care "
            "team has been alerted."
        ),
        "urgency": "emergency",
    },
    "call_surgeon_now": {
        "headline": "Call your surgeon's office now",
        "body": (
            "Call your surgeon's office right away and describe what you're "
            "seeing. If you can't reach them within an hour, or things get "
            "worse, go to the emergency department. Your care team has been "
            "alerted."
        ),
        "urgency": "urgent",
    },
    "call_care_team_today": {
        "headline": "Your care team will contact you today",
        "body": (
            "We've flagged this for your navigator at Memorial General and "
            "someone will reach out today. If it gets worse before then, call "
            "your surgeon's office or go to the emergency department."
        ),
        "urgency": "same_day",
    },
    "self_care_monitor": {
        "headline": "Keep an eye on it",
        "body": (
            "This doesn't look urgent right now. Keep up your usual routine and "
            "check in again tomorrow. If anything changes or gets worse, report "
            "it here again — you won't be bothering anyone."
        ),
        "urgency": "routine",
    },
}


# ---------------------------------------------------------------------------
# Intake definitions — rendered by the app, evaluated below.
# ---------------------------------------------------------------------------
# Question types: bool | scale | choice. `key` is what evaluate() reads.

CATEGORIES: List[Dict[str, Any]] = [
    {
        "category": "fever",
        "title": "Fever or chills",
        "prompt": "Have you had a fever or chills?",
        "questions": [
            {"key": "temp_f", "type": "scale", "label": "Highest temperature (°F)",
             "min": 96, "max": 105, "step": 0.1, "optional": True},
            {"key": "chills", "type": "bool", "label": "Shaking chills or sweats?"},
            {"key": "confusion", "type": "bool", "label": "New confusion or unusual sleepiness?"},
        ],
    },
    {
        "category": "dvt",
        "title": "Calf pain or swelling",
        "prompt": "Any new pain, swelling, or tightness in your calf?",
        "questions": [
            {"key": "one_sided", "type": "bool", "label": "Is it worse in one leg than the other?"},
            {"key": "calf_pain", "type": "bool", "label": "Pain or tenderness in the calf?"},
            {"key": "swelling", "type": "bool", "label": "New swelling in that leg?"},
            {"key": "warm_red", "type": "bool", "label": "Is the skin warm or red there?"},
        ],
    },
    {
        "category": "pe",
        "title": "Chest pain or breathing trouble",
        "prompt": "Any chest pain or trouble breathing?",
        "questions": [
            {"key": "chest_pain", "type": "bool", "label": "Chest pain or pressure?"},
            {"key": "short_of_breath", "type": "bool", "label": "Short of breath at rest?"},
            {"key": "worse_breathing_in", "type": "bool", "label": "Worse when you breathe in?"},
            {"key": "coughing_blood", "type": "bool", "label": "Coughing up blood?"},
        ],
    },
    {
        "category": "wound",
        "title": "Incision changes",
        "prompt": "How does your incision look?",
        "questions": [
            {"key": "drainage", "type": "choice", "label": "Any drainage?",
             "options": ["none", "clear", "cloudy", "foul_smelling"]},
            {"key": "redness_spreading", "type": "bool", "label": "Is redness spreading outward?"},
            {"key": "opening", "type": "bool", "label": "Is the incision coming open?"},
            {"key": "warm_to_touch", "type": "bool", "label": "Warm to the touch?"},
        ],
    },
    {
        "category": "pain",
        "title": "Pain not controlled",
        "prompt": "Is your pain under control?",
        "questions": [
            {"key": "pain_score", "type": "scale", "label": "Pain right now (0–10)",
             "min": 0, "max": 10, "step": 1},
            {"key": "meds_not_helping", "type": "bool", "label": "Pain medicine isn't helping?"},
            {"key": "sudden_change", "type": "bool", "label": "Did it get worse suddenly?"},
        ],
    },
    {
        "category": "fall",
        "title": "A fall",
        "prompt": "Did you fall?",
        "questions": [
            {"key": "fell", "type": "bool", "label": "Did you fall or nearly fall?"},
            {"key": "hit_head", "type": "bool", "label": "Did you hit your head?"},
            {"key": "cannot_bear_weight", "type": "bool", "label": "Can't put weight on the leg now?"},
            {"key": "new_pain", "type": "bool", "label": "New pain since the fall?"},
        ],
    },
]

CATEGORY_CODES = {c["category"] for c in CATEGORIES}


def _truthy(answers: Dict[str, Any], key: str) -> bool:
    return bool(answers.get(key))


def _num(answers: Dict[str, Any], key: str) -> Optional[float]:
    value = answers.get(key)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate(category: str, answers: Dict[str, Any]) -> Dict[str, Any]:
    """Score one red-flag report.

    Returns {severity, guidance_code, reasons[], title}. Unknown categories
    raise ValueError so the router can 400 rather than silently store junk.
    """
    if category not in CATEGORY_CODES:
        raise ValueError(f"unknown red-flag category: {category}")

    reasons: List[str] = []
    severity = "green"
    guidance = "self_care_monitor"

    if category == "fever":
        temp = _num(answers, "temp_f")
        if temp is not None and temp >= 101.0:
            severity, guidance = "red", "call_surgeon_now"
            reasons.append(f"Temperature {temp:.1f}°F (≥101.0)")
        elif temp is not None and temp >= 100.4:
            severity, guidance = "yellow", "call_care_team_today"
            reasons.append(f"Temperature {temp:.1f}°F (100.4–100.9)")
        if _truthy(answers, "confusion"):
            severity, guidance = "red", "go_to_ed"
            reasons.append("New confusion or unusual sleepiness")
        elif _truthy(answers, "chills") and severity == "green":
            severity, guidance = "yellow", "call_care_team_today"
            reasons.append("Shaking chills reported")

    elif category == "dvt":
        signs = sum(
            _truthy(answers, k)
            for k in ("one_sided", "calf_pain", "swelling", "warm_red")
        )
        if _truthy(answers, "one_sided") and signs >= 2:
            severity, guidance = "red", "call_surgeon_now"
            reasons.append("One-sided calf findings — needs same-day assessment")
        elif signs >= 2:
            severity, guidance = "yellow", "call_care_team_today"
            reasons.append("Two or more calf findings")
        elif signs == 1:
            severity, guidance = "yellow", "self_care_monitor"
            reasons.append("Single calf finding")

    elif category == "pe":
        if _truthy(answers, "coughing_blood"):
            severity, guidance = "red", "call_911"
            reasons.append("Coughing up blood")
        elif _truthy(answers, "chest_pain") or _truthy(answers, "short_of_breath"):
            severity, guidance = "red", "call_911"
            reasons.append("Chest pain or shortness of breath at rest")
        elif _truthy(answers, "worse_breathing_in"):
            severity, guidance = "red", "go_to_ed"
            reasons.append("Pain worse on inspiration")

    elif category == "wound":
        drainage = str(answers.get("drainage") or "none")
        if drainage in ("cloudy", "foul_smelling"):
            severity, guidance = "red", "call_surgeon_now"
            reasons.append(f"Drainage: {drainage.replace('_', ' ')}")
        elif drainage == "clear":
            severity, guidance = "yellow", "call_care_team_today"
            reasons.append("Clear drainage")
        if _truthy(answers, "opening"):
            severity, guidance = "red", "call_surgeon_now"
            reasons.append("Incision opening")
        if _truthy(answers, "redness_spreading"):
            if severity != "red":
                severity, guidance = "red", "call_surgeon_now"
            reasons.append("Spreading redness")
        elif _truthy(answers, "warm_to_touch") and severity == "green":
            severity, guidance = "yellow", "call_care_team_today"
            reasons.append("Incision warm to touch")

    elif category == "pain":
        score = _num(answers, "pain_score")
        if score is not None and score >= 8:
            severity, guidance = "red", "call_surgeon_now"
            reasons.append(f"Pain {int(score)}/10")
        elif score is not None and score >= 6:
            severity, guidance = "yellow", "call_care_team_today"
            reasons.append(f"Pain {int(score)}/10")
        if _truthy(answers, "sudden_change"):
            severity, guidance = "red", "call_surgeon_now"
            reasons.append("Sudden worsening")
        elif _truthy(answers, "meds_not_helping") and severity == "green":
            severity, guidance = "yellow", "call_care_team_today"
            reasons.append("Pain medicine not helping")

    elif category == "fall":
        if _truthy(answers, "hit_head"):
            severity, guidance = "red", "go_to_ed"
            reasons.append("Head strike during fall")
        elif _truthy(answers, "cannot_bear_weight"):
            severity, guidance = "red", "go_to_ed"
            reasons.append("Cannot bear weight after fall")
        elif _truthy(answers, "fell"):
            severity, guidance = "yellow", "call_care_team_today"
            reasons.append("Fall reported")
            if _truthy(answers, "new_pain"):
                reasons.append("New pain since the fall")

    title_map = {c["category"]: c["title"] for c in CATEGORIES}
    return {
        "severity": severity,
        "guidance_code": guidance,
        "guidance": GUIDANCE[guidance],
        "reasons": reasons,
        "title": title_map[category],
    }


def queue_title(category: str, severity: str, reasons: List[str]) -> str:
    """Short provider-facing title for the triage queue row."""
    label = {c["category"]: c["title"] for c in CATEGORIES}[category]
    lead = reasons[0] if reasons else label
    prefix = "Red flag" if severity == "red" else "Symptom watch"
    return f"{prefix}: {lead}"
