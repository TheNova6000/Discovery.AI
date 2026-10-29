"""Student discovery: turn a conversation into a validated CourseDesignBrief.

This is deliberately staged rather than a giant form.  Each turn extracts what
the learner actually said, then asks the single most useful next question.  When
the learner says "you decide", the engine records an explicit assumption instead
of pretending the learner supplied a syllabus.

The deterministic path is the product default.  An optional LLM refinement runs
only when a provider key is configured, and a failure falls back silently to the
same deterministic extraction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import llm
from .models import CourseDesignBrief, SyllabusTopic, utcnow

_NEGATIVE = re.compile(
    r"\b(not sure|no idea|no syllabus|you decide|your call|whatever|don'?t know|"
    r"no preference|up to you|surprise me|nothing specific|either way)\b",
    re.IGNORECASE,
)
_STOP = re.compile(r"[.!?\n]")

_QUESTIONS = {
    "topic": (
        "What do you want to learn, and what do you want to be able to do with it "
        "once you have learned it?"
    ),
    "goal": (
        "What do you want to be able to do with {topic} when you are done? "
        "A concrete outcome is more useful than \u201cunderstand it better\u201d."
    ),
    "syllabus": (
        "Do you have a syllabus or a list of topics that must be covered? Paste it, "
        "or say \u201cyou decide\u201d and I will draft a provisional outline you can edit."
    ),
    "time": (
        "How much time can you realistically give this each week, and by when would "
        "you like to reach your goal?"
    ),
    "background": (
        "What do you already know about this area, and what has been difficult for you before?"
    ),
    "project": (
        "What would you like to build? A capstone idea, or the kind of project that "
        "would actually be useful to you?"
    ),
    "methods": (
        "How do you prefer to learn: worked examples, code-first, Socratic questioning, "
        "Feynman teach-back, reading sources, or hands-on projects? Pick any that fit."
    ),
}

_METHOD_WORDS = {
    "feynman": "feynman",
    "teach-back": "feynman",
    "teach back": "feynman",
    "explain it": "feynman",
    "visual": "visual",
    "diagram": "visual",
    "code": "code-first",
    "programming": "code-first",
    "worked example": "worked-examples",
    "example": "worked-examples",
    "socratic": "socratic",
    "question": "socratic",
    "project": "project-based",
    "hands-on": "project-based",
    "hands on": "project-based",
    "reading": "reading",
    "paper": "reading",
    "video": "video",
    "exercise": "retrieval-practice",
    "practice": "retrieval-practice",
    "quiz": "retrieval-practice",
}

_DEPTH_WORDS = {
    "beginner": "introductory",
    "from scratch": "introductory",
    "intro": "introductory",
    "basics": "introductory",
    "advanced": "advanced",
    "deep": "advanced",
    "expert": "advanced",
    "research": "research",
    "paper": "research",
}


@dataclass
class DiscoveryTurn:
    text: str
    brief: CourseDesignBrief
    done: bool
    next_question: str = ""
    missing: list[str] = field(default_factory=list)
    llm_used: bool = False


def _first_sentence(text: str) -> str:
    match = _STOP.search(text)
    return (text[: match.start()] if match else text).strip()


def _split_items(text: str) -> list[str]:
    """Split a pasted list into topics without inventing any."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    items: list[str] = []
    if len(lines) > 1:
        for line in lines:
            cleaned = re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", line).strip()
            if cleaned:
                items.append(cleaned)
    else:
        single = lines[0] if lines else text
        parts = re.split(r"[;]|,\s*|\s+and\s+|\n", single)
        items = [p.strip(" .") for p in parts if p.strip(" .")]
    cleaned_items = []
    for item in items:
        item = re.sub(r"\s+", " ", item).strip()
        if 2 <= len(item) <= 90:
            cleaned_items.append(item)
    return cleaned_items[:12]


def _extract_number(text: str, units: str) -> Optional[float]:
    match = re.search(rf"(\d+(?:\.\d+)?)\s*{units}", text, re.IGNORECASE)
    return float(match.group(1)) if match else None


def _extract_topic(text: str) -> Optional[str]:
    lowered = text.lower()
    if "i want to learn" in lowered or "i'd like to learn" in lowered:
        pattern = r"(?:want to|'d like to|would like to)\s+(?:learn|study|understand|master)\s+(.+)"
    else:
        pattern = r"(?:learn|study|understand|master|get better at|course (?:on|about)|about)\s+(.+)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    clause = _first_sentence(match.group(1)).strip(" .:")
    # Purpose clauses are the goal, not the topic: "binary search trees so I can
    # pass my exam" -> "binary search trees" (became a whole-sentence research
    # topic and graph entity -- verify_chat.py, 2026-10-28).
    clause = re.split(
        r"\s+(?:so(?: that)?\s+i\b|so i can|in order to|because|since|for my|for an?|to pass|to get|to build|to become|to prepare|before)\b",
        clause, maxsplit=1, flags=re.IGNORECASE,
    )[0].strip(" .:")
    # "linear algebra, calculus and probability" -> the first item is the topic,
    # the rest is syllabus material handled separately.
    clause = re.split(r",|;|\s+and\s+", clause)[0].strip()
    if not clause or len(clause) > 80:
        return None
    return clause


def _extract_goal(text: str, topic: str) -> Optional[str]:
    match = re.search(r"(?:so (?:that )?i can|goal is to|i want to be able to|in order to)\s+(.+)", text, re.IGNORECASE)
    if match:
        goal = _first_sentence(match.group(1)).strip(" .:")
        if goal:
            return goal
    match = re.search(r"\bfor\s+((?:my|a|an|the)\s+[^.;\n]{3,90})", text, re.IGNORECASE)
    if match:
        return f"Use {topic} for {match.group(1).strip(' .')}"
    return None


def _infer_topics(topic: str) -> list[SyllabusTopic]:
    """A provisional scaffold, explicitly labelled `inferred`.

    These are not research claims about the subject; they are editable course
    structure that the learner must approve before anything is generated.
    """
    t = topic.strip()
    if not t:
        return []
    titles = [
        f"Foundations of {t}",
        f"Core concepts and vocabulary in {t}",
        f"Methods and tools used in {t}",
        f"Applying {t} to your stated goal",
    ]
    return [
        SyllabusTopic(
            title=title,
            description="Provisional topic inferred from the learner's goal; edit or replace it before approving.",
            source="inferred",
            confidence=0.35,
            estimated_hours=3.0,
        )
        for title in titles
    ]


def _next_unanswered(brief: CourseDesignBrief) -> Optional[str]:
    missing = brief.missing_required()
    if "topic" in missing:
        return "topic"
    if "goal" in missing:
        return "goal"
    if "syllabus" in missing:
        return "syllabus"
    if "weekly_hours" in missing:
        return "time"
    optional = []
    if not brief.prior_knowledge and not brief.gaps and not brief.projects.project_style:
        optional.append("background")
    if brief.projects.wants_capstone and not brief.projects.capstone_idea:
        optional.append("project")
    if not brief.learning_preferences:
        optional.append("methods")
    for qid in optional:
        if brief.asked.count(qid) == 0:
            return qid
    return None


def _ask(brief: CourseDesignBrief, qid: str) -> str:
    brief.asked.append(qid)
    brief.updated_at = utcnow()
    return _QUESTIONS[qid].format(topic=brief.topic or "this subject")


def _apply_defaults(brief: CourseDesignBrief) -> None:
    """Resolve a stuck required field with a labelled assumption, never silently."""
    if not brief.goal and brief.topic:
        brief.goal = f"Reach a {brief.depth} level in {brief.topic}."
        note = "Goal inferred from the topic because no concrete outcome was supplied."
        if note not in brief.assumptions:
            brief.assumptions.append(note)
    if len(brief.syllabus_topics) < 2:
        inferred = _infer_topics(brief.topic)
        if inferred:
            brief.merge_topics(inferred)
            note = "Provisional syllabus inferred from your goal because no syllabus was supplied."
            if note not in brief.assumptions:
                brief.assumptions.append(note)
    if brief.weekly_hours is None:
        brief.weekly_hours = 5.0
        note = "Assumed 5 study hours per week because no schedule was supplied."
        if note not in brief.assumptions:
            brief.assumptions.append(note)
    if brief.target_weeks is None:
        total = sum(t.estimated_hours for t in brief.syllabus_topics) or 12.0
        brief.target_weeks = max(2, round(total / max(brief.weekly_hours, 1.0)))
    brief.updated_at = utcnow()


def _extract(brief: CourseDesignBrief, message: str, last_question: Optional[str]) -> None:
    text = message.strip()
    if not text:
        return

    if not brief.topic:
        topic = _extract_topic(text)
        if not topic and len(text.split()) <= 8:
            topic = _first_sentence(text)
        if topic:
            brief.topic = topic

    if brief.topic and not brief.goal:
        goal = _extract_goal(text, brief.topic)
        if goal:
            brief.goal = goal
    if brief.topic and not brief.goal and last_question == "goal" and len(text.split()) >= 2:
        brief.goal = _first_sentence(text)[:400]
    if brief.topic and not brief.goal and last_question in (None, "topic") and len(text) > 12:
        # A statement of purpose that did not match a keyword is still useful,
        # but only when it is clearly about the learner's own aim.
        if re.search(r"\b(want|hope|aim|plan|need)\b", text, re.IGNORECASE):
            brief.goal = _first_sentence(text)[:300]

    for word, depth in _DEPTH_WORDS.items():
        if word in text.lower():
            brief.depth = depth  # type: ignore[assignment]
            break

    hours = _extract_number(text, r"(?:hours?|hrs?)\s*(?:/|per|a|each)?\s*(?:week|wk)")
    if hours is None:
        hours = _extract_number(text, r"(?:hours?|hrs?)\s*(?:per week|/week)")
    if hours is not None and 0 < hours <= 80:
        brief.weekly_hours = hours
    weeks_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:weeks?|wks?)\b", text, re.IGNORECASE)
    if weeks_match:
        prefix = text[max(0, weeks_match.start() - 8) : weeks_match.start()].lower()
        if not re.search(r"(?:per|a|each|every|/)\s*$", prefix):
            weeks = float(weeks_match.group(1))
            if 1 <= weeks <= 200:
                brief.target_weeks = int(weeks)

    negative = bool(_NEGATIVE.search(text))
    mentions_syllabus = bool(
        re.search(r"\b(syllabus|topics?|modules?|curriculum|units?|chapters?)\b", text, re.IGNORECASE)
    )
    if negative and (last_question == "syllabus" or mentions_syllabus):
        if not brief.syllabus_topics and brief.topic:
            brief.merge_topics(_infer_topics(brief.topic))
            note = "Provisional syllabus inferred from your goal because no syllabus was supplied."
            if note not in brief.assumptions:
                brief.assumptions.append(note)
    else:
        candidate_text = text
        # A reply that plainly answers a DIFFERENT question (background or time)
        # is not a syllabus, even while the syllabus question is pending: the live
        # chat turned "I know basic biology and chemistry" into the topic
        # "chemistry" and "about 4 hours a week for 6 weeks" into another.
        answers_other_slot = not mentions_syllabus and bool(
            hours is not None
            or weeks_match
            or re.search(r"\b(i know|i've (?:used|studied)|i have (?:used|studied)|familiar with|background in|experience (?:with|in))\b",
                         text, re.IGNORECASE)
        )
        if (last_question == "syllabus" or mentions_syllabus or "\n" in text) and not answers_other_slot:
            items = _split_items(candidate_text)
            # Drop an item that is merely the topic repeated, and obvious prose.
            items = [
                i
                for i in items
                if i.lower() != brief.topic.strip().lower()
                and not i.lower().startswith(("i want", "i have", "i know", "my goal"))
                and len(i.split()) <= 12
            ]
            if len(items) >= 2:
                brief.merge_topics(
                    [
                        SyllabusTopic(
                            title=i[:120],
                            description="Supplied or pasted by the learner during discovery.",
                            source="learner",
                            confidence=0.9,
                            estimated_hours=3.0,
                        )
                        for i in items
                    ]
                )
            elif last_question == "syllabus" and len(items) == 1 and len(brief.syllabus_topics) < 2:
                brief.merge_topics(
                    [SyllabusTopic(title=items[0][:120], source="learner", confidence=0.8)]
                )

    if re.search(r"\b(no experience|beginner|from scratch|never (?:used|studied)|starting fresh)\b", text, re.IGNORECASE):
        gap = "No prior experience reported"
        if gap not in brief.gaps:
            brief.gaps.append(gap)
    for pattern in (
        r"(?:i know|i've used|i have used|familiar with|experience (?:with|in)|background in)\s+([^.;\n]{2,120})",
    ):
        for match in re.finditer(pattern, text, re.IGNORECASE):
            known = match.group(1).strip(" .")
            if known and known.lower() not in {p.lower() for p in brief.prior_knowledge}:
                brief.prior_knowledge.append(known)

    if re.search(r"\b(capstone|final project|main project|build|create|ship)\b", text, re.IGNORECASE):
        match = re.search(
            r"(?:capstone|final project|main project|build|create|ship)\s+(?:a|an|the)?\s*([^.;\n]{3,160})",
            text,
            re.IGNORECASE,
        )
        if match:
            idea = match.group(1).strip(" .")
            if idea and not brief.projects.capstone_idea:
                brief.projects.capstone_idea = idea

    if re.search(r"\b(no (?:mini[- ]?)?projects?|theory only|no capstone)\b", text, re.IGNORECASE):
        brief.projects.wants_mini_projects = "theory only" not in text.lower()
        brief.projects.wants_capstone = "no capstone" not in text.lower() and "theory only" not in text.lower()

    for word, method in _METHOD_WORDS.items():
        if word in text.lower() and method not in brief.learning_preferences:
            brief.learning_preferences.append(method)

    if re.search(r"\b(?:budget|hardware|gpu|laptop|offline|no internet)\b", text, re.IGNORECASE):
        clause = _first_sentence(text)
        if clause and clause not in brief.constraints and len(clause) < 200:
            brief.constraints.append(clause)

    brief.updated_at = utcnow()


def _merge_llm(brief: CourseDesignBrief, extracted: "llm.LLMDiscoveryExtraction") -> None:
    if extracted.topic and not brief.topic:
        brief.topic = extracted.topic.strip()[:120]
    if extracted.goal and not brief.goal:
        brief.goal = extracted.goal.strip()[:400]
    if extracted.motivation and not brief.motivation:
        brief.motivation = extracted.motivation.strip()[:400]
    if extracted.depth:
        brief.depth = extracted.depth
    if extracted.weekly_hours and brief.weekly_hours is None and 0 < extracted.weekly_hours <= 80:
        brief.weekly_hours = float(extracted.weekly_hours)
    if extracted.target_weeks and brief.target_weeks is None and 1 <= extracted.target_weeks <= 200:
        brief.target_weeks = int(extracted.target_weeks)
    if extracted.syllabus_topics:
        brief.merge_topics(
            [
                SyllabusTopic(title=t[:120], source="learner", confidence=0.8)
                for t in extracted.syllabus_topics
                if t.strip()
            ]
        )
    for field_name in ("prior_knowledge", "gaps", "constraints", "learning_preferences", "assumptions"):
        current = getattr(brief, field_name)
        for value in getattr(extracted, field_name):
            if value and value not in current:
                current.append(value)
    if extracted.capstone_idea and not brief.projects.capstone_idea:
        brief.projects.capstone_idea = extracted.capstone_idea.strip()[:300]


def _summary(brief: CourseDesignBrief) -> str:
    topics = brief.syllabus_topics
    source = "inferred" if topics and all(t.source == "inferred" for t in topics) else "supplied"
    lines = [
        "I have enough to design the first plan.",
        "",
        f"- Topic: {brief.topic}",
        f"- Goal: {brief.goal}",
        f"- Depth: {brief.depth}",
        f"- Syllabus: {len(topics)} topics ({source}) \u2014 "
        + "; ".join(t.title for t in topics[:6])
        + ("\u2026" if len(topics) > 6 else ""),
        f"- Time: {brief.weekly_hours:g} h/week"
        + (f", target {brief.target_weeks} weeks" if brief.target_weeks else ""),
    ]
    if brief.prior_knowledge:
        lines.append("- Prior knowledge: " + "; ".join(brief.prior_knowledge[:4]))
    if brief.projects.capstone_idea:
        lines.append("- Capstone idea: " + brief.projects.capstone_idea)
    if brief.learning_preferences:
        lines.append("- Preferred methods: " + ", ".join(brief.learning_preferences))
    if brief.assumptions:
        lines.append("")
        lines.append("Assumptions to check: " + " ".join(brief.assumptions))
    lines.append("")
    lines.append(
        "Next: review the brief and start the research pass. Research only proposes a plan \u2014 "
        "nothing is generated until you approve it."
    )
    return "\n".join(lines)


async def respond(
    brief: CourseDesignBrief,
    message: str,
    *,
    use_llm: Optional[bool] = None,
) -> DiscoveryTurn:
    """One discovery turn. Input brief is not mutated."""
    updated = brief.model_copy(deep=True)
    last_question = updated.asked[-1] if updated.asked else None

    _extract(updated, message, last_question)

    llm_used = False
    wants_llm = llm.available() if use_llm is None else use_llm
    if wants_llm:
        extracted = await llm.refine_discovery(message, updated.topic)
        if extracted is not None:
            _merge_llm(updated, extracted)
            llm_used = True

    if _NEGATIVE.search(message) and len(updated.syllabus_topics) < 2:
        _apply_defaults(updated)

    next_qid = _next_unanswered(updated)
    if next_qid and updated.asked.count(next_qid) >= 2:
        # Asked twice without an answer: record the assumption and move on.
        _apply_defaults(updated)
        next_qid = _next_unanswered(updated)

    if next_qid:
        question = _ask(updated, next_qid)
        acknowledgement = ""
        if updated.topic and last_question in (None, "topic"):
            acknowledgement = f"Got it \u2014 {updated.topic}."
            if updated.goal:
                acknowledgement += f" Aim: {updated.goal}."
            acknowledgement += "\n\n"
        elif updated.syllabus_topics and last_question == "syllabus":
            acknowledgement = f"Noted {len(updated.syllabus_topics)} topics.\n\n"
        elif updated.weekly_hours is not None and last_question == "time":
            acknowledgement = f"Got it \u2014 {updated.weekly_hours:g} hours per week.\n\n"
        return DiscoveryTurn(
            text=acknowledgement + question,
            brief=updated,
            done=False,
            next_question=question,
            missing=updated.missing_required(),
            llm_used=llm_used,
        )

    _apply_defaults(updated)
    missing = updated.missing_required()
    return DiscoveryTurn(
        text=_summary(updated),
        brief=updated,
        done=not missing,
        next_question="",
        missing=missing,
        llm_used=llm_used,
    )


def greeting() -> str:
    return (
        "I'm Tuni'n. Before any course is generated, I need to understand what you are aiming for. "
        + _QUESTIONS["topic"]
    )
