"""Static reference catalogs: PT exercises and phase-gated checklists.

Single source of truth for content that is the same for every patient.
db/migrate_app.py seeds app.pt_exercise and app.checklist_item from these
lists (INSERT … ON CONFLICT UPDATE), so editing here and re-running the
migration propagates without touching patient rows.

Exercise content is generic SHFFT post-op mobility work, phase-gated. Video
URLs are placeholders for the MVP — no media pipeline (see TODO.md).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

VIDEO_PLACEHOLDER = "https://placeholder.catalyst.local/pt/{code}.mp4"


def _video(code: str) -> str:
    return VIDEO_PLACEHOLDER.format(code=code)


# ---------------------------------------------------------------------------
# PT exercise library — phase: snf | transition_home | home_recovery
# ---------------------------------------------------------------------------

_RAW_EXERCISES: List[Dict[str, Any]] = [
    # Early / facility phase — bed and seated work
    {
        "code": "ankle_pumps",
        "phase": "snf",
        "name": "Ankle pumps",
        "description": (
            "Lying or sitting, point your toes away from you, then pull them "
            "back toward your knee. Keep it slow and steady."
        ),
        "default_sets": 3,
        "default_reps": 15,
        "weight_bearing_note": "Safe at any weight-bearing level.",
    },
    {
        "code": "quad_sets",
        "phase": "snf",
        "name": "Quad sets",
        "description": (
            "Lying with your leg straight, tighten the muscle on top of your "
            "thigh and press the back of your knee down. Hold 5 seconds."
        ),
        "default_sets": 3,
        "default_reps": 10,
        "weight_bearing_note": "No weight through the leg — safe if non-weight-bearing.",
    },
    {
        "code": "glute_sets",
        "phase": "snf",
        "name": "Glute squeezes",
        "description": "Squeeze your buttock muscles together, hold 5 seconds, release.",
        "default_sets": 3,
        "default_reps": 10,
        "weight_bearing_note": "Safe at any weight-bearing level.",
    },
    {
        "code": "heel_slides",
        "phase": "snf",
        "name": "Heel slides",
        "description": (
            "Lying on your back, slide your heel toward your buttock, bending "
            "the knee as far as is comfortable, then straighten."
        ),
        "default_sets": 2,
        "default_reps": 10,
        "weight_bearing_note": "Stay within the range your therapist set.",
    },
    {
        "code": "seated_knee_ext",
        "phase": "snf",
        "name": "Seated knee extension",
        "description": (
            "Sitting in a chair, straighten your operated leg out in front of "
            "you, hold 3 seconds, lower slowly."
        ),
        "default_sets": 3,
        "default_reps": 10,
        "weight_bearing_note": "Seated — no weight through the leg.",
    },
    # Transition home — standing work with support
    {
        "code": "sit_to_stand",
        "phase": "transition_home",
        "name": "Sit to stand",
        "description": (
            "From a firm chair with arms, push up to standing, then lower back "
            "down under control. Use your hands as much as you need to."
        ),
        "default_sets": 3,
        "default_reps": 8,
        "weight_bearing_note": "Follow your weight-bearing instructions on the operated leg.",
    },
    {
        "code": "standing_hip_abduction",
        "phase": "transition_home",
        "name": "Standing side leg raise",
        "description": (
            "Holding a counter, lift your operated leg out to the side, keeping "
            "your toes pointed forward. Lower slowly."
        ),
        "default_sets": 2,
        "default_reps": 10,
        "weight_bearing_note": "Hold support at all times.",
    },
    {
        "code": "standing_marching",
        "phase": "transition_home",
        "name": "Standing marching",
        "description": (
            "Holding a counter, lift one knee toward your chest like a slow "
            "march, then the other."
        ),
        "default_sets": 2,
        "default_reps": 10,
        "weight_bearing_note": "Hold support at all times.",
    },
    {
        "code": "walker_ambulation",
        "phase": "transition_home",
        "name": "Walking with your walker",
        "description": (
            "Walk with your walker inside the house. Walker first, then your "
            "operated leg, then your other leg."
        ),
        "default_sets": 4,
        "default_reps": 1,
        "weight_bearing_note": "Keep to the weight-bearing limit your surgeon set.",
    },
    {
        "code": "heel_toe_raises",
        "phase": "transition_home",
        "name": "Heel and toe raises",
        "description": (
            "Holding a counter, rise onto your toes, lower, then rock back onto "
            "your heels."
        ),
        "default_sets": 2,
        "default_reps": 12,
        "weight_bearing_note": "Only once you are weight-bearing as tolerated.",
    },
    # Home recovery — progression toward independence
    {
        "code": "cane_ambulation",
        "phase": "home_recovery",
        "name": "Walking with a cane",
        "description": (
            "Walk with a cane in the hand opposite your operated leg. Cane and "
            "operated leg move together."
        ),
        "default_sets": 3,
        "default_reps": 1,
        "weight_bearing_note": "Only after your therapist clears you to step down from the walker.",
    },
    {
        "code": "step_ups",
        "phase": "home_recovery",
        "name": "Step ups",
        "description": (
            "At the bottom of a staircase, holding the rail, step up with your "
            "stronger leg, bring the operated leg up, then step back down."
        ),
        "default_sets": 2,
        "default_reps": 8,
        "weight_bearing_note": "Hold the handrail. Up with the good leg, down with the operated leg.",
    },
    {
        "code": "mini_squats",
        "phase": "home_recovery",
        "name": "Mini squats",
        "description": (
            "Holding a counter, bend your knees a small amount as if starting "
            "to sit, then straighten. Keep your heels down."
        ),
        "default_sets": 2,
        "default_reps": 10,
        "weight_bearing_note": "Small range only — stop before pain.",
    },
    {
        "code": "side_stepping",
        "phase": "home_recovery",
        "name": "Side stepping",
        "description": "Holding a counter, take slow steps sideways along it and back.",
        "default_sets": 2,
        "default_reps": 10,
        "weight_bearing_note": "Hold support at all times.",
    },
    {
        "code": "stair_practice",
        "phase": "home_recovery",
        "name": "Stair practice",
        "description": (
            "With the handrail, practice a few stairs. Up with the stronger leg "
            "first, down with the operated leg first."
        ),
        "default_sets": 1,
        "default_reps": 4,
        "weight_bearing_note": "Only with someone nearby until you feel steady.",
    },
    {
        "code": "walking_endurance",
        "phase": "home_recovery",
        "name": "Walking for endurance",
        "description": (
            "Walk a little further than yesterday, with whatever aid you're "
            "using. Turn back before you get tired."
        ),
        "default_sets": 1,
        "default_reps": 1,
        "weight_bearing_note": "Use your walking aid until your therapist says otherwise.",
    },
]

PT_EXERCISES: List[Dict[str, Any]] = [
    {**ex, "video_url": _video(ex["code"]), "sort_order": i}
    for i, ex in enumerate(_RAW_EXERCISES)
]

# Exercises expected per day, per phase — denominator for adherence.
EXPECTED_DAILY_EXERCISES = {
    "inpatient": 0,
    "snf": 3,
    "irf": 3,
    "transition_home": 3,
    "home_recovery": 3,
    "completed": 0,
}


# ---------------------------------------------------------------------------
# Phase-gated checklists
# ---------------------------------------------------------------------------

_SNF_READINESS: List[Dict[str, Any]] = [
    ("walk_50ft", "I can walk about 50 feet with my walker", True,
     "This is the usual minimum for getting around at home safely."),
    ("transfer_bed_chair", "I can get in and out of bed and a chair on my own", True,
     "Using equipment is fine — the question is whether you need another person."),
    ("toilet_independent", "I can use the toilet without help", True, None),
    ("stairs_if_needed", "I can manage the stairs I'll have at home", False,
     "Skip if there are no stairs where you're going."),
    ("understands_wb", "I know how much weight I can put on my leg", True,
     "Your surgeon set a specific limit. If you're unsure, say no."),
    ("meds_reviewed", "Someone has gone over my medicines with me", True, None),
    ("home_support", "I'll have help at home when I need it", False, None),
    ("equipment_ready", "My walker and any equipment will be at home", False, None),
    ("appointments_known", "I know when my follow-up appointments are", False, None),
    ("transport_ready", "I have a ride home arranged", False, None),
]

_HOME_SAFETY: List[Dict[str, Any]] = [
    ("rugs_removed", "Loose rugs and mats are picked up or taped down", True,
     "Rugs are the most common trip hazard after hip surgery."),
    ("walkways_clear", "Walkways are clear of cords, boxes, and clutter", True, None),
    ("night_lights", "There's a light I can reach on the way to the bathroom", True, None),
    ("bathroom_grab_bars", "There's something solid to hold onto in the bathroom", True,
     "A grab bar — not a towel rail or the sink."),
    ("raised_toilet", "The toilet is high enough, or has a raised seat", False, None),
    ("shower_nonslip", "There's a non-slip mat in the shower or tub", False, None),
    ("chair_with_arms", "I have a firm chair with arms to sit in", False,
     "Low, soft chairs make standing up harder and can strain the hip."),
    ("phone_reachable", "I can reach a phone from where I sit and sleep", True, None),
    ("stair_handrail", "The stairs have a handrail I can use", False,
     "Skip if there are no stairs."),
    ("pets_managed", "I have a plan for pets underfoot", False, None),
    ("frequent_items_low", "Things I use often are within easy reach", False,
     "So you're not bending or reaching up high."),
]

CHECKLIST_ITEMS: List[Dict[str, Any]] = [
    *[
        {
            "checklist_code": "snf_discharge_readiness",
            "item_code": code,
            "phase": "snf",
            "label": label,
            "help_text": help_text,
            "critical": critical,
            "sort_order": i,
        }
        for i, (code, label, critical, help_text) in enumerate(_SNF_READINESS)
    ],
    *[
        {
            "checklist_code": "home_safety",
            "item_code": code,
            "phase": "transition_home",
            "label": label,
            "help_text": help_text,
            "critical": critical,
            "sort_order": i,
        }
        for i, (code, label, critical, help_text) in enumerate(_HOME_SAFETY)
    ],
]

CHECKLIST_META = {
    "snf_discharge_readiness": {
        "title": "Ready to go home?",
        "intro": (
            "Your team uses this to plan your discharge. Answer honestly — a "
            "\"no\" here means someone helps you with it before you leave, not "
            "that you're stuck at the facility."
        ),
        "phase": "snf",
    },
    "home_safety": {
        "title": "Home safety check",
        "intro": (
            "Most falls after hip surgery happen at home in the first few "
            "weeks. Walk through your home and check what's already done."
        ),
        "phase": "transition_home",
    },
}


def checklist_codes_for_phase(
    phase: str, post_acute_phase: Optional[str] = None
) -> List[str]:
    """Which checklists this episode can fill in right now.

    Gating is disposition-aware, not purely phase-aware: an episode discharged
    to a SNF/IRF keeps its discharge-readiness checklist for the whole episode,
    because readiness is revisited repeatedly while the facility plans the
    handoff — and because the nominal post-acute length of stay in phases.py is
    an approximation, so a patient can be modelled as "home" while the facility
    still has open readiness items.

    Home safety opens at discharge and stays open, so it can be revisited as
    equipment arrives.
    """
    codes: List[str] = []
    if phase in ("snf", "irf") or post_acute_phase in ("snf", "irf"):
        codes.append("snf_discharge_readiness")
    if phase in ("snf", "irf", "transition_home", "home_recovery"):
        codes.append("home_safety")
    return codes
