"""Curriculum compiler.

Turns an approved-shape `CourseDesignBrief` plus a `ResearchBundle` into a
validated `CourseProposal`.  It is deterministic: the same brief and research
bundle produce the same plan, with no model call.  The plan is a *proposal* --
`status=AWAITING_APPROVAL` -- and the orchestrator refuses to generate modules
until the learner approves that exact version.

Epistemic rule this file follows strictly: without a configured Discovery.AI
endpoint there is no engine that can verify subject claims, so lesson bodies are
structured study guides over real retrieved sources, never invented facts.  The
retrieved title/snippet/URL is quoted with provenance, and the proposal carries
that limitation explicitly.
"""

from __future__ import annotations

import re
from typing import Optional

from .models import (
    CapstonePlan,
    CourseDesignBrief,
    CourseProposal,
    Exercise,
    ExerciseKind,
    ExerciseOption,
    Lesson,
    MiniProject,
    ModulePlan,
    ResearchBundle,
    ResearchMode,
    SourceReference,
    SyllabusMapping,
    SyllabusTopic,
)

LEARNING_METHODS: dict[str, str] = {
    "feynman": "Explain the idea aloud in plain language, then find where the explanation breaks.",
    "retrieval-practice": "Close the notes and answer from memory before checking.",
    "spaced-repetition": "Revisit earlier concepts in later modules instead of one massed review.",
    "interleaving": "Mix related concepts in practice so discrimination is learned, not just repetition.",
    "worked-examples": "Study a complete worked example, then solve a near-transfer task with less support.",
    "socratic": "Answer a chain of why/how questions instead of receiving a summary.",
    "project-based": "Build a small artefact that forces the concept into contact with reality.",
    "metacognitive-reflection": "Record what you expected, what happened, and what you will change.",
    "reading-sources": "Read primary or reference sources and annotate them against the objective.",
}

_DEFAULT_METHODS = ["feynman", "retrieval-practice", "worked-examples", "metacognitive-reflection"]

_PREFERENCE_MAP = {
    "feynman": "feynman",
    "visual": "worked-examples",
    "code-first": "project-based",
    "worked-examples": "worked-examples",
    "socratic": "socratic",
    "project-based": "project-based",
    "reading": "reading-sources",
    "video": "worked-examples",
    "retrieval-practice": "retrieval-practice",
}


def slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned[:48] or "module"


def select_methods(brief: CourseDesignBrief) -> list[str]:
    chosen: list[str] = []
    for preference in brief.learning_preferences:
        method = _PREFERENCE_MAP.get(preference, preference)
        if method in LEARNING_METHODS and method not in chosen:
            chosen.append(method)
    for method in _DEFAULT_METHODS:
        if method not in chosen:
            chosen.append(method)
    return chosen[:6]


def _objectives(topic: SyllabusTopic, goal: str) -> list[str]:
    return [
        f"Explain {topic.title} in your own words, with one concrete example.",
        f"Apply {topic.title} to a small task that moves you toward: {goal}.",
        f"Identify one limitation, failure mode, or open question in {topic.title}.",
    ]


def _source_lines(sources: list[SourceReference]) -> str:
    if not sources:
        return (
            "_No external source was retrieved for this topic._ This lesson is a plan-only study "
            "guide. Use your own syllabus or notes, and treat any statement you add as your own."
        )
    lines = []
    for source in sources:
        snippet = (source.snippet or "").replace("\n", " ").strip()
        if len(snippet) > 260:
            snippet = snippet[:257] + "\u2026"
        suffix = f" \u2014 {snippet}" if snippet else ""
        lines.append(f"- [{source.title}]({source.url}){suffix}")
    return "\n".join(lines)


def _lesson_markdown(
    *,
    brief: CourseDesignBrief,
    topic: SyllabusTopic,
    module_title: str,
    lesson_title: str,
    focus: str,
    sources: list[SourceReference],
    teach_back: bool = False,
) -> str:
    goals = "\n".join(f"- {o}" for o in _objectives(topic, brief.goal))
    parts = [
        f"# {lesson_title}",
        "",
        f"**Module:** {module_title}  ",
        f"**Estimated time:** 25\u201340 minutes  ",
        f"**Focus:** {focus}",
        "",
        "## Why this matters for your goal",
        "",
        f"Your stated goal is: *{brief.goal or brief.topic}*. This lesson treats {topic.title} as a "
        "means to that goal, not as a topic to memorise in isolation.",
        "",
        "## What you will be able to do",
        "",
        goals,
        "",
        "## Study path",
        "",
        "1. Read the sources below with the objectives in mind. Annotate only what answers them.",
        "2. Close the sources and write the explanation in your own words. Name what you are unsure about.",
        "3. Compare your explanation with the sources. Correct it, and note the correction.",
        "4. Do the module exercises. If you cannot explain an answer, that is the next thing to study.",
        "",
        "## Sources",
        "",
        _source_lines(sources),
        "",
        "## Boundaries",
        "",
    ]
    if sources:
        parts.append(
            "The links and excerpts above are real retrieved results. This study guide does not "
            "claim that every statement in a source is correct: read it, and record disagreement "
            "rather than smoothing it over."
        )
    else:
        parts.append(
            "No source was retrieved, so this lesson deliberately does not assert subject facts. "
            "It gives you the structure and the questions; you supply the material."
        )
    if teach_back:
        parts += [
            "",
            "## Feynman teach-back",
            "",
            f"Explain {topic.title} to someone who has never studied it, in under 200 words, without "
            "jargon. Then write one sentence describing where your explanation would break down. "
            "Submit it as the teach-back exercise; a rubric shows what a strong explanation contains.",
        ]
    return "\n".join(parts)


def _exercise_ids(course_id: str, sequence: int) -> dict[str, str]:
    base = f"{course_id}_m{sequence:02d}"
    return {
        "mcq": f"{base}_mcq",
        "short": f"{base}_short",
        "feynman": f"{base}_feynman",
        "project": f"{base}_project",
    }


def _mcq(
    *,
    exercise_id: str,
    topic: SyllabusTopic,
    objectives: list[str],
    distractor: str,
) -> Exercise:
    correct = objectives[0]
    options = [
        ExerciseOption(id="a", text=correct),
        ExerciseOption(id="b", text=distractor),
        ExerciseOption(id="c", text="Memorise every definition before attempting any application."),
    ]
    return Exercise(
        id=exercise_id,
        kind=ExerciseKind.MCQ,
        prompt=f"Which of these is a stated objective of the module on {topic.title}?",
        concepts=[topic.title],
        options=options,
        answer_key="a",
        rubric=["Correct option references a real objective stated in the lesson."],
        hints=["Look at the lesson's \u201cWhat you will be able to do\u201d section."],
        max_score=1.0,
        estimated_minutes=2,
    )


def _short_answer(exercise_id: str, topic: SyllabusTopic) -> Exercise:
    return Exercise(
        id=exercise_id,
        kind=ExerciseKind.SHORT_ANSWER,
        prompt=(
            f"In 3\u20135 sentences, explain {topic.title} in your own words. Include one thing it is "
            "used for and one limitation or open question."
        ),
        concepts=[topic.title],
        rubric=[
            "Defines the concept rather than repeating its name.",
            "Gives a concrete use or example.",
            "States a real limitation or open question.",
            "Uses the learner's own words.",
        ],
        hints=["If you cannot state a limitation, say what you are still unsure about."],
        max_score=1.0,
        estimated_minutes=10,
        manual_only=True,
    )


def _feynman(exercise_id: str, topic: SyllabusTopic) -> Exercise:
    return Exercise(
        id=exercise_id,
        kind=ExerciseKind.FEYNMAN,
        prompt=(
            f"Teach {topic.title} to someone who has never studied it, in under 200 words and "
            "without jargon. Finish with one sentence: \u201cThis explanation would break if\u2026\u201d"
        ),
        concepts=[topic.title],
        rubric=[
            "Plain language, no unexplained jargon.",
            "A concrete analogy or example.",
            "Names where the explanation breaks down.",
            "Stays within the word limit.",
        ],
        hints=["A good teach-back is short and specific, not a summary of everything."],
        max_score=1.0,
        estimated_minutes=12,
        manual_only=True,
    )


def _mini_project(topic: SyllabusTopic, brief: CourseDesignBrief, sequence: int) -> MiniProject:
    return MiniProject(
        title=f"Mini-project {sequence}: apply {topic.title}",
        brief=(
            f"Produce a small, inspectable artefact that applies {topic.title} to your goal "
            f"(\u201c{brief.goal}\u201d). Prefer something you can show in five minutes over something "
            "large and unfinished."
        ),
        skills=[topic.title, "applying a concept", "self-assessment"],
        deliverables=[
            "A 300\u2013500 word write-up: what you built or analysed, and why.",
            "The artefact itself (code, diagram, experiment log, or annotated source).",
            "A short self-assessment against the rubric, naming the weakest part.",
        ],
        constraints=list(brief.constraints[:4])
        + ["No dependency on a service you cannot access.", "Keep it finishable in the module's time budget."],
        rubric=[
            "The artefact addresses the stated goal, not a generic tutorial.",
            "The write-up explains decisions and trade-offs.",
            "The self-assessment is specific about what is weak.",
        ],
        extension_tasks=[
            "Add one test, check, or counter-example that could falsify your claim.",
            "Rewrite the write-up for a reader who does not share your background.",
        ],
        contributes_to_capstone=f"Provides a component or a tested assumption for: {brief.goal}",
    )


def _capstone(brief: CourseDesignBrief, modules: list[ModulePlan]) -> CapstonePlan:
    idea = brief.projects.capstone_idea or brief.goal or f"A applied project in {brief.topic}"
    milestones = []
    for index, module in enumerate(modules, start=1):
        milestones.append(f"After module {index} ({module.title}): record the capability it adds to the capstone.")
    milestones.append("Final milestone: demonstrate the capstone and defend two design decisions.")
    return CapstonePlan(
        title=idea if len(idea) <= 90 else idea[:87] + "\u2026",
        problem=(
            f"Build or investigate something that demonstrates: {brief.goal or idea}. "
            "The capstone must integrate the course's core topics rather than repeat one module."
        ),
        milestones=milestones,
        deliverables=[
            "A working artefact or a rigorous written investigation.",
            "A README stating the problem, the approach, and how to inspect the result.",
            "A test/verification plan with evidence that it was carried out.",
            "A short reflection: what you would do differently, and what remains unresolved.",
        ],
        constraints=list(brief.constraints[:6]),
        rubric=[
            "Integrates at least three module concepts.",
            "Claims are supported by the artefact or by cited sources.",
            "Limitations and unresolved questions are stated honestly.",
            "A reader can reproduce or inspect the result.",
        ],
        testing_strategy=[
            "Define the checks before building.",
            "Run them and keep the output, including failures.",
            "Separate what was verified from what was assumed.",
        ],
        final_demonstration="A five-minute walkthrough plus a short question session on trade-offs and failure modes.",
    )


def _module(
    *,
    course_id: str,
    proposal_id: str,
    sequence: int,
    topic: SyllabusTopic,
    brief: CourseDesignBrief,
    sources: list[SourceReference],
    methods: list[str],
    distractor: str,
    note: str = "",
) -> ModulePlan:
    objectives = _objectives(topic, brief.goal)
    ids = _exercise_ids(course_id, sequence)
    lesson_one = Lesson(
        id=f"{course_id}_m{sequence:02d}_l1",
        title=f"{topic.title}: concepts and vocabulary",
        objectives=objectives[:2],
        content_md=_lesson_markdown(
            brief=brief,
            topic=topic,
            module_title=topic.title,
            lesson_title=f"{topic.title}: concepts and vocabulary",
            focus="Build an accurate mental model before practising.",
            sources=sources,
        ),
        source_ids=[s.id for s in sources],
        estimated_minutes=30,
    )
    lesson_two = Lesson(
        id=f"{course_id}_m{sequence:02d}_l2",
        title=f"{topic.title}: worked example and teach-back",
        objectives=objectives,
        content_md=_lesson_markdown(
            brief=brief,
            topic=topic,
            module_title=topic.title,
            lesson_title=f"{topic.title}: worked example and teach-back",
            focus="Turn recognition into explanation and application.",
            sources=sources,
            teach_back=True,
        ),
        worked_example_md=(
            "Use the sources to find one complete example of "
            f"{topic.title}. Reconstruct it without looking, then compare. Record every place your "
            "reconstruction drifted from the source."
        ),
        teach_back_prompt=(
            f"Explain {topic.title} to a beginner in under 200 words, then say where the explanation breaks."
        ),
        source_ids=[s.id for s in sources],
        estimated_minutes=40,
    )
    exercises = [
        _mcq(exercise_id=ids["mcq"], topic=topic, objectives=objectives, distractor=distractor),
        _short_answer(ids["short"], topic),
        _feynman(ids["feynman"], topic),
    ]
    mini = _mini_project(topic, brief, sequence) if brief.projects.wants_mini_projects else None

    return ModulePlan(
        id=f"{course_id}_mod{sequence:02d}",
        course_id=course_id,
        proposal_id=proposal_id,
        sequence=sequence,
        title=topic.title,
        purpose=(
            f"Build working command of {topic.title} and connect it explicitly to your goal: "
            f"{brief.goal}"
        ),
        objectives=objectives,
        concepts=[topic.title],
        estimated_hours=round(max(topic.estimated_hours, 3.0), 1),
        teaching_strategies=methods[:4],
        lessons=[lesson_one, lesson_two],
        exercises=exercises,
        mini_project=mini,
        assessment_strategy=(
            "One deterministic comprehension check, one rubric-scored explanation, and one Feynman "
            "teach-back. Mastery starts at 0.0 and only moves with repeated evidence."
        ),
        completion_criteria=[
            "Attempt every exercise in the module.",
            "Submit the post-module feedback.",
            "State one thing you still cannot explain.",
        ],
        evidence_refs=[s.id for s in sources],
        source_topic_id=topic.id,
        adaptation_note=note,
    )


def compile_proposal(
    *,
    course_id: str,
    brief: CourseDesignBrief,
    research: Optional[ResearchBundle],
    version: int = 1,
) -> CourseProposal:
    methods = select_methods(brief)
    proposal_id = f"{course_id}_prop{version:02d}"
    topics = list(brief.syllabus_topics)
    while len(topics) < 2:
        # The two-module buffer requires at least two modules.  This is a
        # structural split, labelled, not invented subject content.
        base = topics[0].title if topics else (brief.topic or "Foundations")
        topics.append(
            SyllabusTopic(
                title=f"{base}: application",
                description="Structural module added so the two-module buffer has a first step.",
                source="inferred",
                confidence=0.35,
            )
        )

    modules: list[ModulePlan] = []
    mappings: list[SyllabusMapping] = []
    all_minis: list[MiniProject] = []

    for index, topic in enumerate(topics, start=1):
        topic_research = None
        if research:
            topic_research = next((t for t in research.topics if t.topic_id == topic.id), None)
        sources = list(topic_research.sources) if topic_research else []
        coverage = "covered" if sources else "partial"
        note = ""
        if not sources:
            note = "Planned without a retrieved source; treat the module as a study guide to edit."
        distractor = (
            topics[(index) % len(topics)].title + ": explain it without applying it"
            if len(topics) > 1
            else "Skip every application task."
        )
        module = _module(
            course_id=course_id,
            proposal_id=proposal_id,
            sequence=index,
            topic=topic,
            brief=brief,
            sources=sources,
            methods=methods,
            distractor=distractor,
            note=note,
        )
        if module.mini_project:
            all_minis.append(module.mini_project)
        modules.append(module)
        mappings.append(
            SyllabusMapping(
                topic_id=topic.id,
                topic_title=topic.title,
                coverage=coverage,
                module_ids=[module.id],
                objectives=module.objectives,
                evidence=[s.id for s in sources],
                notes=(
                    f"Planned in module {index}. Sources retrieved: {len(sources)}."
                    if sources
                    else f"Planned in module {index}; no source retrieved."
                ),
            )
        )

    # Prerequisites are the real, explicit linear order chosen here -- stated as a
    # design decision rather than presented as a discovered dependency graph.
    for previous, current in zip(modules, modules[1:]):
        current.prerequisites = [previous.title]

    total_hours = sum(m.estimated_hours for m in modules)
    limitations: list[str] = []
    assumptions = list(brief.assumptions)
    research_mode = research.mode if research else ResearchMode.OFFLINE
    if research:
        limitations.extend(research.limitations)
        if research.mode == ResearchMode.DIRECT_RETRIEVAL:
            limitations.append(
                "Module order is a deliberate linear sequence for a first course. It is not a "
                "researched prerequisite graph; edit it at approval if your syllabus implies another order."
            )
        if research.status != "complete":
            limitations.append(
                f"Research status was {research.status!r}, so some topics have thin or no evidence."
            )
    else:
        limitations.append("No research bundle was attached; this plan is ungrounded and must be edited.")

    weekly = brief.weekly_hours or 5.0
    weeks = brief.target_weeks or max(2, round(total_hours / max(weekly, 1.0)))
    proposal = CourseProposal(
        id=proposal_id,
        course_id=course_id,
        version=version,
        title=f"{brief.topic or 'Personal course'}: a research-guided plan",
        description=(
            f"A {len(modules)}-module plan built around your goal: {brief.goal or brief.topic}. "
            f"Designed for roughly {weekly:g} hours per week over about {weeks} weeks."
        ),
        audience=f"Learner aiming to: {brief.goal}" if brief.goal else "Self-directed learner",
        objectives=[
            f"Reach a {brief.depth} level in {brief.topic}.",
            f"Produce evidence toward: {brief.goal}" if brief.goal else f"Apply {brief.topic}.",
            "Explain core concepts without notes and identify their limits.",
        ],
        prerequisites=list(brief.prior_knowledge)
        or ["No formal prerequisite was supplied; the plan starts from foundations."],
        estimated_effort_hours=total_hours,
        completion_plan=(
            f"{len(modules)} modules, delivered two at a time. Each module ends with assessment and "
            "feedback; the next buffer is replanned from that evidence."
        ),
        syllabus_mapping=mappings,
        modules=modules,
        mini_projects=all_minis,
        capstone=_capstone(brief, modules) if brief.projects.wants_capstone else None,
        capstone_opted_out=not brief.projects.wants_capstone,
        learning_methods=methods,
        assessment_strategy=[
            "Deterministic MCQ grading where an answer key exists.",
            "Rubric-scored short answers and teach-backs; heuristic scores are partial by design.",
            "Mastery starts at 0.0 with zero evidence and requires repeated, varied evidence to rise.",
            "Post-module feedback is combined with attempts, never treated as correctness on its own.",
        ],
        limitations=limitations,
        assumptions=assumptions,
        research_mode=research_mode,
        sources=list(research.sources) if research else [],
        status="awaiting_approval",
    )
    if not brief.projects.wants_capstone:
        # validate_plan requires a capstone; an explicit opt-out is a real learner
        # choice, so record the reason instead of silently inventing one.
        proposal.limitations.append(
            "The learner opted out of a capstone; the proposal validator flags the missing capstone "
            "until they either approve that scope change or add one."
        )
    return proposal


def apply_edits(proposal: CourseProposal, edits: dict) -> CourseProposal:
    """Apply learner edits to a proposal, producing a new draft version.

    Only learner-editable fields are accepted.  Module content cannot be rewritten
    here because that would bypass validation and artifact generation.
    """
    updated = proposal.model_copy(deep=True)
    if edits.get("title"):
        updated.title = str(edits["title"])[:200]
    if edits.get("description"):
        updated.description = str(edits["description"])[:2000]
    if isinstance(edits.get("learning_methods"), list):
        chosen = [m for m in edits["learning_methods"] if m in LEARNING_METHODS]
        if chosen:
            updated.learning_methods = chosen
    for module_id, module_edit in (edits.get("module_edits") or {}).items():
        module = next((m for m in updated.modules if m.id == module_id), None)
        if module is None:
            continue
        if module_edit.get("title"):
            module.title = str(module_edit["title"])[:160]
        if module_edit.get("purpose"):
            module.purpose = str(module_edit["purpose"])[:600]
        if isinstance(module_edit.get("objectives"), list):
            objectives = [str(o)[:300] for o in module_edit["objectives"] if str(o).strip()]
            if objectives:
                module.objectives = objectives
        if isinstance(module_edit.get("estimated_hours"), (int, float)):
            module.estimated_hours = round(max(0.5, float(module_edit["estimated_hours"])), 1)
    removed = edits.get("remove_optional_project")
    if removed:
        updated.mini_projects = [p for p in updated.mini_projects if p.title != removed]
        for module in updated.modules:
            if module.mini_project and module.mini_project.title == removed:
                module.mini_project = None
    updated.estimated_effort_hours = round(sum(m.estimated_hours for m in updated.modules), 1)
    return updated
