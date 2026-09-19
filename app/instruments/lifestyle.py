"""
Lifestyle R3 — the institution's own instrument, so unlike DASS-21 it carries
no licence restriction and no published norms. That means it CAN legitimately
be gathered conversationally instead of as a form, which is where the "subtle"
part of the brief actually belongs.

Each slot below is something the model is allowed to fill from ordinary
conversation ("I've been up till 3 most nights") without ever asking the
question verbatim. Slots left empty at the end of a session are simply empty —
the model does not interrogate to complete the set.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# name -> (type hint for the extractor, what counts as evidence)
SLOTS: dict[str, tuple[str, str]] = {
    "sleep_hours":        ("int 0-10",  "hours slept on a typical night"),
    "sleep_disturbances": ("int 0-10",  "times woken per night"),
    "exercise_band":      ("str",       "walking, sport or outdoor activity per week"),
    "breakfast_missed":   ("int 0-7",   "days per week breakfast is skipped"),
    "meals_missed":       ("int 0-7",   "days per week three meals are not eaten"),
    "water_litres":       ("int 0-6",   "litres of water per day"),
    "fruit_veg_days":     ("int 0-7",   "days per week with fruit or vegetables"),
    "solitude_band":      ("str",       "silence, prayer, meditation or self-reflection per week"),
    "practice_years":     ("str",       "how long any such practice has been kept up"),
    "screen_hours":       ("int 0-10",  "mobile or television hours per day"),
    "active_hours":       ("int 0-10",  "hours physically active per day"),
    "strengths":          ("list[str]", "what the student says they are good at or relies on"),
    "weaknesses":         ("list[str]", "what the student names as their own difficulty"),
    "self_love":          ("int 0-10",  "how content they say they are with themselves"),
    "happy_activities":   ("list[str]", "what they do that reliably lifts them"),
    "discomfort_type":    ("str",       "physical, stress-related, both, or neither"),
    "issue_duration":     ("str",       "how long the difficulty has been going on"),
}

# Lifestyle findings that are worth surfacing to a counsellor on their own,
# independent of any DASS score. Thresholds are the clinical side's call —
# these are placeholders for Dr. Dana's team to set.
CONCERN_RULES: tuple[tuple[str, str], ...] = (
    ("sleep_hours",       "<= 5 hours on a typical night"),
    ("sleep_disturbances", ">= 3 wakings per night"),
    ("meals_missed",      ">= 4 days per week"),
    ("screen_hours",      ">= 8 hours per day"),
    ("self_love",         "<= 3 out of 10"),
)


@dataclass
class LifestyleProfile:
    values: dict[str, Any] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)  # slot -> the student's own words

    def fill(self, slot: str, value: Any, quote: str = "") -> None:
        if slot not in SLOTS:
            raise ValueError(f"unknown lifestyle slot: {slot}")
        self.values[slot] = value
        if quote:
            self.evidence[slot] = quote

    @property
    def coverage(self) -> float:
        return len(self.values) / len(SLOTS)

    def concerns(self) -> list[str]:
        out = []
        v = self.values
        if isinstance(v.get("sleep_hours"), int) and v["sleep_hours"] <= 5:
            out.append(f"sleeping about {v['sleep_hours']}h a night")
        if isinstance(v.get("sleep_disturbances"), int) and v["sleep_disturbances"] >= 3:
            out.append(f"waking ~{v['sleep_disturbances']}x a night")
        if isinstance(v.get("meals_missed"), int) and v["meals_missed"] >= 4:
            out.append(f"missing full meals {v['meals_missed']} days a week")
        if isinstance(v.get("screen_hours"), int) and v["screen_hours"] >= 8:
            out.append(f"~{v['screen_hours']}h daily screen time")
        if isinstance(v.get("self_love"), int) and v["self_love"] <= 3:
            out.append(f"self-contentment {v['self_love']}/10")
        return out
