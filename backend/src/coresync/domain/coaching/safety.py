"""Safety rules for the coach.

Every rule here is **code, not prompt**. A prompt instruction can be argued with by a
determined user or drifted past by a model update; a function cannot (docs/10 §7.1).

The layering matters. The calorie floor is a CHECK constraint first, a clamp in the
calculator second, a service validation third, and a prompt instruction last. This module
is the layer that sits between the user and the model — it decides what never reaches the
model, and what never leaves it.

Nothing here calls an LLM. That is deliberate: the triage that decides whether a message
is a disclosure of disordered eating must not itself depend on a network call that can
time out, and it must be exhaustively testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum


class SafetyCategory(StrEnum):
    """Why a message was intercepted.

    Ordered by how the response differs, not by severity — each category needs a
    materially different reply.
    """

    DISORDERED_EATING = "disordered_eating"
    MEDICAL = "medical"
    SELF_HARM = "self_harm"
    MINOR_RESTRICTION = "minor_restriction"
    PROMPT_INJECTION = "prompt_injection"


@dataclass(frozen=True, slots=True)
class SafetyVerdict:
    """The outcome of screening one message.

    ``matched`` records which patterns fired so a flag can be audited later. It
    deliberately holds the *pattern names*, never the message text — a triage event is
    logged without storing what the user said (docs/10 §7.2).
    """

    category: SafetyCategory | None
    matched: tuple[str, ...] = ()

    @property
    def is_blocked(self) -> bool:
        return self.category is not None


# --------------------------------------------------------------------- patterns
# Word-boundary anchored so "fasting" does not fire on "breakfasting", and phrase-based
# where a single word would be far too broad. Every entry is named so a verdict can say
# which rule fired without quoting the user.
_ED_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "purging",
        r"\b(purge|purging|make myself (throw up|sick)|vomit(ing)? after (eating|meals))\b",
    ),
    ("laxatives", r"\b(laxative|diuretic)s?\b.{0,30}\b(weight|lose|burn)\b"),
    ("starvation", r"\b(starv(e|ing) myself|not eat(ing)? (for|at all)|stop eating)\b"),
    ("extreme_fast", r"\b(\d{2,3})\s*(hour|day)s?\s*(water )?fast\b"),
    ("extreme_deficit", r"\b(\d{3,4})\s*(kcal|calories)\b.{0,40}\b(a day|per day|daily)\b"),
    ("compensate", r"\b(burn off|work off|earn) (what|the calories|my (food|meal))\b"),
    ("body_hate", r"\b(hate|disgust(ed|ing)?) (my|with my) (body|stomach|thighs|fat)\b"),
    ("guilt_food", r"\b(bad|guilty|ashamed|punish)\b.{0,20}\b(eating|ate|food|meal)\b"),
    ("thinspo", r"\b(thinspo|proana|pro-ana|bonespo)\b"),
)

_MEDICAL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("injury", r"\b(tore|torn|tear|rupture|fracture|dislocat|sprain|herniat)\w*\b"),
    (
        "pain",
        r"\b(sharp|shooting|chronic|severe) pain\b"
        r"|\bpain (in|when) my (back|knee|shoulder|chest)\b",
    ),
    ("medication", r"\b(medication|prescri(bed|ption)|antidepressant|insulin|steroid|sarm|trt)\b"),
    ("condition", r"\b(diabet|thyroid|pcos|hypertension|pregnan|hypoglyc|anemia|anaemia)\w*\b"),
    ("bloodwork", r"\b(blood ?work|blood test|cholesterol|a1c|hormone panel)\b"),
    ("cardiac", r"\b(chest pain|heart palpitation|fainting|passed out|dizzy spells)\b"),
)

_SELF_HARM_PATTERNS: tuple[tuple[str, str], ...] = (
    ("self_harm", r"\b(kill(ing)? myself|end(ing)? my life|suicid\w*|self.?harm\w*|want to die)\b"),
)

# The user's own free text reaches the model as data. These are attempts to make it read
# as instructions instead (docs/10 §7.4).
_INJECTION_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        "override",
        r"\b(ignore|disregard|forget) (all |any |the |your |my )?"
        r"(previous|prior|above|earlier) (instruction|prompt|rule|message)s?\b",
    ),
    ("role_change", r"\b(you are now|act as|pretend to be|roleplay as|from now on you)\b"),
    (
        "system_probe",
        r"\b(system prompt|your instructions|reveal your|print your (prompt|rules))\b",
    ),
    ("jailbreak", r"\b(dan mode|developer mode|jailbreak|no restrictions|without any filter)\b"),
    ("tool_forgery", r"<\s*/?\s*(tool_call|function_call|system|assistant)\s*>"),
)

_COMPILED: dict[SafetyCategory, tuple[tuple[str, re.Pattern[str]], ...]] = {
    SafetyCategory.SELF_HARM: tuple(
        (name, re.compile(p, re.IGNORECASE)) for name, p in _SELF_HARM_PATTERNS
    ),
    SafetyCategory.DISORDERED_EATING: tuple(
        (name, re.compile(p, re.IGNORECASE)) for name, p in _ED_PATTERNS
    ),
    SafetyCategory.MEDICAL: tuple(
        (name, re.compile(p, re.IGNORECASE)) for name, p in _MEDICAL_PATTERNS
    ),
    SafetyCategory.PROMPT_INJECTION: tuple(
        (name, re.compile(p, re.IGNORECASE)) for name, p in _INJECTION_PATTERNS
    ),
}

# Checked in this order. Self-harm outranks everything; a message that mentions both
# starvation and a medication must be handled as the more serious of the two.
_PRECEDENCE: tuple[SafetyCategory, ...] = (
    SafetyCategory.SELF_HARM,
    SafetyCategory.DISORDERED_EATING,
    SafetyCategory.MEDICAL,
    SafetyCategory.PROMPT_INJECTION,
)


class InputTriage:
    """Screens a message before it reaches the model.

    Heuristics only. docs/10 §7.2 pairs these with a small classifier model; the
    heuristics are the half that must never be unavailable, so they stand alone and the
    classifier is an optional second opinion layered on top.

    Deliberately biased toward false positives on self-harm and eating disorders. The
    cost of wrongly offering support to someone who did not need it is mild awkwardness;
    the cost of missing a real disclosure is not comparable.
    """

    def screen(self, message: str) -> SafetyVerdict:
        if not message or not message.strip():
            return SafetyVerdict(category=None)

        for category in _PRECEDENCE:
            matched = tuple(
                name for name, pattern in _COMPILED[category] if pattern.search(message)
            )
            if matched:
                return SafetyVerdict(category=category, matched=matched)
        return SafetyVerdict(category=None)

    def screen_minor(self, message: str, *, age: int | None) -> SafetyVerdict:
        """Under-18s asking about restriction get the supportive path, not coaching.

        A deficit request that is ordinary from a 30-year-old is not ordinary from a
        15-year-old, and the model is not the right thing to be making that judgement.
        """
        verdict = self.screen(message)
        if verdict.is_blocked:
            return verdict
        if age is not None and age < 18:
            restriction = re.compile(
                r"\b(diet|deficit|cutting|lose (weight|fat)|calorie (limit|target)|fast(ing)?)\b",
                re.IGNORECASE,
            )
            if restriction.search(message):
                return SafetyVerdict(
                    category=SafetyCategory.MINOR_RESTRICTION, matched=("minor_restriction",)
                )
        return SafetyVerdict(category=None)


# ------------------------------------------------------------------- responses
# Written to be short, non-clinical and non-judgemental. The user is never told they have
# a disorder, never lectured, and never blocked from the app (docs/10 §7.2).
SAFE_RESPONSES: dict[SafetyCategory, str] = {
    SafetyCategory.SELF_HARM: (
        "I'm not the right kind of help for this, and I don't want to give you a glib "
        "answer. Please talk to someone who can actually support you — a doctor, or a "
        "crisis line in your country. If you're in immediate danger, call your local "
        "emergency number."
    ),
    SafetyCategory.DISORDERED_EATING: (
        "I'm not going to help with that one. Not as a judgement — it's just outside what "
        "I can do responsibly.\n\n"
        "If food or your body has been weighing on you lately, talking to a doctor or a "
        "registered dietitian is genuinely worth it. Beat (UK), NEDA (US) and local "
        "equivalents have free, confidential lines.\n\n"
        "I'm still here for training questions whenever you want them."
    ),
    SafetyCategory.MEDICAL: (
        "That's a question for a clinician rather than me — I can't diagnose, treat, or "
        "advise on medication or medical conditions, and guessing would be worse than "
        "saying so.\n\n"
        "Once you've got that sorted, I'm happy to work around whatever they tell you."
    ),
    SafetyCategory.MINOR_RESTRICTION: (
        "I don't give calorie or weight-loss advice to under-18s — bodies are still "
        "developing, and that's a conversation for a doctor who knows you.\n\n"
        "What I can help with is training: getting stronger, building a routine, and "
        "learning good technique. Want to start there?"
    ),
    SafetyCategory.PROMPT_INJECTION: (
        "I'll stick to being your coach. Ask me about your training, your numbers, or "
        "your progress and I'll dig in."
    ),
}


# --------------------------------------------------------------- output guards
_OUTPUT_LEAK_PATTERNS: tuple[tuple[str, str], ...] = (
    ("system_prompt_leak", r"(?i)\b(my system prompt|my instructions are|i was instructed to)\b"),
    ("tool_syntax", r"<\s*/?\s*(tool_call|function_call|system)\s*>"),
    ("role_break", r"(?i)\b(i am (now )?(dan|in developer mode)|as an unrestricted)\b"),
)
_COMPILED_OUTPUT = tuple((n, re.compile(p)) for n, p in _OUTPUT_LEAK_PATTERNS)

# Nothing edible is denser than pure fat, and no coach should be emitting a target below
# the documented floor. Both are checked against what the model actually wrote, because a
# model that has been talked into an unsafe number will state it confidently.
MIN_SAFE_CALORIES = Decimal("1200")
MAX_PLAUSIBLE_CALORIES = Decimal("8000")

_CALORIE_MENTION = re.compile(r"(\d{3,5})\s*(?:kcal|calories|cals)\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class OutputVerdict:
    is_safe: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def must_regenerate(self) -> bool:
        return not self.is_safe


class OutputGuard:
    """Checks what the model produced before the user sees it.

    Two classes of failure: the model leaking its own scaffolding, and the model stating a
    number that is outside safe bounds. The second matters more — a leaked prompt is
    embarrassing, an unsafe calorie target is the thing the whole safety design exists to
    prevent (docs/10 §7.5).
    """

    def inspect(self, response: str) -> OutputVerdict:
        reasons: list[str] = []

        for name, pattern in _COMPILED_OUTPUT:
            if pattern.search(response):
                reasons.append(name)

        for match in _CALORIE_MENTION.finditer(response):
            value = Decimal(match.group(1))
            if value < MIN_SAFE_CALORIES:
                reasons.append("calorie_below_floor")
                break
            if value > MAX_PLAUSIBLE_CALORIES:
                reasons.append("calorie_implausible")
                break

        return OutputVerdict(is_safe=not reasons, reasons=tuple(reasons))


FALLBACK_RESPONSE = (
    "I couldn't put together a good answer to that one. Try asking me a different way, "
    "or ask about something specific in your training and I'll pull the numbers."
)

# Shown on every AI surface. Stated once explicitly at onboarding and acknowledged
# there (docs/10 §7.3).
DISCLAIMER = (
    "Coaching guidance, not medical advice. Talk to a qualified professional about "
    "injuries, medication or medical conditions."
)
