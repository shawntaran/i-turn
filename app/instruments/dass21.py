"""
DASS-21 — Depression Anxiety Stress Scales, 21-item short form.

Copyright Psychology Foundation of Australia. Free to use for research and
clinical work WITHOUT modification. The items below are verbatim and must
stay that way: paraphrasing them breaks both the licence and the norms that
the severity bands are derived from.

Everything in this module is deterministic Python. The language model never
scores, never assigns a severity band, and never edits an item. Its only job
in a DASS block is to map a free-text reply ("yeah, pretty often") onto an
integer 0-3, and even that is confirmed back to the student before it counts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# ---------------------------------------------------------------------------
# Response anchors
# ---------------------------------------------------------------------------
# NOTE FOR THE PSYCHOLOGY SIDE:
# The Holistic Health Care Form 2 currently labels these
# NEVER / SOMETIMES / OFTEN / ALMOST ALWAYS.
# That is a *frequency* scale. Published DASS-21 norms are built on a
# *degree* scale (below). They are not interchangeable, and swapping them
# makes the severity cutoffs non-comparable to any published sample.
# Recommend reverting the Google Form to these before pilot data collection.
ANCHORS: dict[int, str] = {
    0: "Did not apply to me at all",
    1: "Applied to me to some degree, or some of the time",
    2: "Applied to me to a considerable degree, or a good part of the time",
    3: "Applied to me very much, or most of the time",
}

TIME_FRAME = "over the past week"

Subscale = Literal["depression", "anxiety", "stress"]


@dataclass(frozen=True)
class Item:
    number: int          # 1-21, matches the printed form
    text: str            # verbatim, do not edit
    subscale: Subscale


ITEMS: tuple[Item, ...] = (
    Item(1, "I found it hard to wind down", "stress"),
    Item(2, "I was aware of dryness of my mouth", "anxiety"),
    Item(3, "I couldn't seem to experience any positive feeling at all", "depression"),
    Item(4, "I experienced breathing difficulty (e.g. excessively rapid breathing, "
            "breathlessness in the absence of physical exertion)", "anxiety"),
    Item(5, "I found it difficult to work up the initiative to do things", "depression"),
    Item(6, "I tended to over-react to situations", "stress"),
    Item(7, "I experienced trembling (e.g. in the hands)", "anxiety"),
    Item(8, "I felt that I was using a lot of nervous energy", "stress"),
    Item(9, "I was worried about situations in which I might panic and make a fool of myself", "anxiety"),
    Item(10, "I felt that I had nothing to look forward to", "depression"),
    Item(11, "I found myself getting agitated", "stress"),
    Item(12, "I found it difficult to relax", "stress"),
    Item(13, "I felt down-hearted and blue", "depression"),
    Item(14, "I was intolerant of anything that kept me from getting on with what I was doing", "stress"),
    Item(15, "I felt I was close to panic", "anxiety"),
    Item(16, "I was unable to become enthusiastic about anything", "depression"),
    Item(17, "I felt I wasn't worth much as a person", "depression"),
    Item(18, "I felt that I was rather touchy", "stress"),
    Item(19, "I was aware of the action of my heart in the absence of physical exertion "
             "(e.g. sense of heart rate increase, heart missing a beat)", "anxiety"),
    Item(20, "I felt scared without any good reason", "anxiety"),
    Item(21, "I felt that life was meaningless", "depression"),
)

BY_NUMBER: dict[int, Item] = {i.number: i for i in ITEMS}

# Severity cutoffs apply to the DOUBLED subscale score (DASS-21 -> DASS-42 scale).
# (lower_bound_inclusive, label)
_BANDS: dict[Subscale, tuple[tuple[int, str], ...]] = {
    "depression": ((28, "Extremely severe"), (21, "Severe"), (14, "Moderate"), (10, "Mild"), (0, "Normal")),
    "anxiety":    ((20, "Extremely severe"), (15, "Severe"), (10, "Moderate"), (8, "Mild"),  (0, "Normal")),
    "stress":     ((34, "Extremely severe"), (26, "Severe"), (19, "Moderate"), (15, "Mild"), (0, "Normal")),
}

# Any subscale at or above this band triggers a counsellor referral regardless
# of what the conversation looked like. Clinical side owns this constant.
REFERRAL_BANDS = {"Severe", "Extremely severe"}

# Item 17 ("I felt I wasn't worth much as a person") and item 21 ("I felt that
# life was meaningless") are not suicidality items and must not be read as
# such. DASS-21 contains no risk item — risk detection lives in safety.py and
# runs independently of this instrument.
FLAG_FOR_HUMAN_REVIEW = (17, 21)


@dataclass
class Result:
    raw: dict[Subscale, int]
    scaled: dict[Subscale, int]
    bands: dict[Subscale, str]
    answered: int
    complete: bool
    referral_indicated: bool
    review_flags: list[int] = field(default_factory=list)

    def plain_summary(self) -> str:
        """Plain-language bands, the way the VC proposal specifies they are shown."""
        return " · ".join(
            f"{s.capitalize()}: {self.bands[s]}" for s in ("depression", "anxiety", "stress")
        )


def band_for(subscale: Subscale, scaled_score: int) -> str:
    for lower, label in _BANDS[subscale]:
        if scaled_score >= lower:
            return label
    return "Normal"


def score(responses: dict[int, int]) -> Result:
    """
    responses: {item_number: 0|1|2|3}. Partial sets are allowed so the UI can
    show progress, but `complete` stays False and bands are provisional until
    all 21 are in.
    """
    for num, val in responses.items():
        if num not in BY_NUMBER:
            raise ValueError(f"item {num} is not part of DASS-21")
        if val not in (0, 1, 2, 3):
            raise ValueError(f"item {num}: response must be 0-3, got {val!r}")

    raw: dict[Subscale, int] = {"depression": 0, "anxiety": 0, "stress": 0}
    for num, val in responses.items():
        raw[BY_NUMBER[num].subscale] += val

    scaled = {k: v * 2 for k, v in raw.items()}
    bands = {k: band_for(k, v) for k, v in scaled.items()}  # type: ignore[arg-type]
    complete = len(responses) == len(ITEMS)

    return Result(
        raw=raw,
        scaled=scaled,
        bands=bands,
        answered=len(responses),
        complete=complete,
        referral_indicated=complete and any(b in REFERRAL_BANDS for b in bands.values()),
        review_flags=[n for n in FLAG_FOR_HUMAN_REVIEW if responses.get(n, 0) >= 2],
    )


def next_items(responses: dict[int, int], block_size: int = 3) -> list[Item]:
    """Next small batch to deliver. Order is fixed — never shuffled, never skipped."""
    remaining = [i for i in ITEMS if i.number not in responses]
    return remaining[:block_size]


CONSENT_PROMPT = (
    "There's a short standard questionnaire I can walk you through — 21 statements, "
    f"and for each one you tell me how much it applied to you {TIME_FRAME}. "
    "Takes about three minutes. It gives us something more solid than a guess, and "
    "you can stop at any point. Want to do it?"
)
