"""Versioned Markdown artifact generation.

Every module is written as a directory of small files rather than one monolithic
document:

    README.md          module overview, objectives, completion criteria
    lesson_XX.md       lesson bodies
    exercises.md       student-facing exercises (no answers)
    answer_key.md      deterministic keys + rubrics, kept separate
    rubric.md          assessment rubric
    sources.md         provenance for this module
    module.json        machine-readable module metadata

A new version writes a new directory.  Earlier versions and anything the learner
has added outside these files are never overwritten.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Optional

from . import store
from .curriculum import slug
from .models import ArtifactRecord, CourseProposal, ExerciseKind, ModulePlan

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_ROOT = _REPO_ROOT / "data" / "tunin_courses"

_PLACEHOLDER = re.compile(r"\{(?:topic|goal|title|module)\}")


def artifact_root() -> Path:
    configured = os.environ.get("TUNIN_ARTIFACT_DIR")
    return Path(configured) if configured else DEFAULT_ARTIFACT_ROOT


def module_dir(module: ModulePlan) -> Path:
    return artifact_root() / module.course_id / f"m{module.sequence:02d}-{slug(module.title)}-v{module.version}"


def _write(path: Path, content: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_module(module: ModulePlan, proposal: CourseProposal) -> list[str]:
    errors: list[str] = []
    if not module.objectives:
        errors.append(f"{module.id}: no objectives")
    if not module.lessons:
        errors.append(f"{module.id}: no lessons")
    if not module.exercises:
        errors.append(f"{module.id}: no exercises")
    for lesson in module.lessons:
        if len(lesson.content_md.strip()) < 120:
            errors.append(f"{module.id}/{lesson.id}: lesson body is too thin to publish")
        if _PLACEHOLDER.search(lesson.content_md):
            errors.append(f"{module.id}/{lesson.id}: unresolved template placeholder")
    kinds = {e.kind for e in module.exercises}
    if ExerciseKind.MCQ not in kinds:
        errors.append(f"{module.id}: no deterministic comprehension check")
    if not module.completion_criteria:
        errors.append(f"{module.id}: no completion criteria")
    source_ids = {s.id for s in proposal.sources}
    for ref in module.evidence_refs:
        if ref not in source_ids:
            errors.append(f"{module.id}: evidence reference {ref!r} is not in the proposal source manifest")
    return errors


def _readme(module: ModulePlan, proposal: CourseProposal) -> str:
    lines = [
        f"# Module {module.sequence}: {module.title}",
        "",
        f"**Course:** {proposal.title}  ",
        f"**Estimated effort:** {module.estimated_hours:g} hours  ",
        f"**Version:** {module.version}  ",
        "",
        "## Purpose",
        "",
        module.purpose,
        "",
        "## Learning objectives",
        "",
        *[f"- {o}" for o in module.objectives],
        "",
        "## Lessons",
        "",
        *[f"- [{lesson.title}]({_lesson_filename(index)})" for index, lesson in enumerate(module.lessons, start=1)],
        "",
        "## Teaching strategies",
        "",
        *[f"- **{m}**" for m in module.teaching_strategies],
        "",
        "## Completion criteria",
        "",
        *[f"- {c}" for c in module.completion_criteria],
        "",
        "## Files",
        "",
        "- `exercises.md` \u2014 attempt these before opening the answer key.",
        "- `answer_key.md` \u2014 deterministic keys and rubrics; open only after attempting.",
        "- `rubric.md` \u2014 how the open-ended work is judged.",
        "- `sources.md` \u2014 what this module is grounded in, and what it is not.",
        "",
    ]
    if module.adaptation_note:
        lines += ["## Adaptation note", "", module.adaptation_note, ""]
    return "\n".join(lines)


def _lesson_filename(index: int) -> str:
    return f"lesson_{index:02d}.md"


def _exercises(module: ModulePlan) -> str:
    lines = [f"# Exercises \u2014 {module.title}", "", "Attempt every exercise before opening `answer_key.md`.", ""]
    for index, exercise in enumerate(module.exercises, start=1):
        lines += [
            f"## {index}. {exercise.kind.value.replace('_', ' ').title()}",
            "",
            exercise.prompt,
            "",
            f"*Concepts:* {', '.join(exercise.concepts) or 'general'}  ",
            f"*Estimated time:* {exercise.estimated_minutes} minutes  ",
            f"*Points:* {exercise.max_score:g}",
            "",
        ]
        if exercise.options:
            for option in exercise.options:
                lines.append(f"- **{option.id}.** {option.text}")
            lines.append("")
        if exercise.hints:
            lines += ["<details><summary>Hint</summary>", ""]
            lines += [f"- {h}" for h in exercise.hints]
            lines += ["", "</details>", ""]
        if exercise.manual_only:
            lines += ["_This exercise is graded against a rubric; the score is partial until reviewed._", ""]
    if module.mini_project:
        project = module.mini_project
        lines += [
            "## Mini-project",
            "",
            f"### {project.title}",
            "",
            project.brief,
            "",
            "**Deliverables**",
            "",
            *[f"- {d}" for d in project.deliverables],
            "",
            "**Constraints**",
            "",
            *[f"- {c}" for c in project.constraints],
            "",
            "**Extension tasks**",
            "",
            *[f"- {t}" for t in project.extension_tasks],
            "",
        ]
    return "\n".join(lines)


def _answer_key(module: ModulePlan) -> str:
    lines = [
        f"# Answer key and grading notes \u2014 {module.title}",
        "",
        "> Student-facing content is in `exercises.md`. Do not read this before attempting.",
        "",
    ]
    for index, exercise in enumerate(module.exercises, start=1):
        lines += [f"## {index}. {exercise.kind.value.replace('_', ' ').title()}", ""]
        if exercise.kind == ExerciseKind.MCQ:
            correct = next((o for o in exercise.options if o.id == exercise.answer_key), None)
            lines += [
                f"**Correct option:** {exercise.answer_key}"
                + (f" \u2014 {correct.text}" if correct else ""),
                "",
                "Deterministic grading: the submitted option id is compared with the key.",
                "",
            ]
        else:
            lines += [
                "**Manual/rubric grading.** No deterministic answer is claimed.",
                "",
                "A strong answer contains:",
                "",
                *[f"- {c}" for c in exercise.rubric],
                "",
            ]
    lines += [
        "## Mastery note",
        "",
        "One correct answer never implies mastery. The learner model starts at 0.0 and needs repeated, "
        "varied evidence before an ADVANCE decision.",
        "",
    ]
    return "\n".join(lines)


def _rubric(module: ModulePlan) -> str:
    lines = [f"# Assessment rubric \u2014 {module.title}", "", "| Criterion | What it means |", "|---|---|"]
    seen: set[str] = set()
    for exercise in module.exercises:
        for criterion in exercise.rubric:
            if criterion not in seen:
                seen.add(criterion)
                lines.append(f"| {criterion} | Assessed in `{exercise.id}` |")
    if module.mini_project:
        for criterion in module.mini_project.rubric:
            if criterion not in seen:
                seen.add(criterion)
                lines.append(f"| {criterion} | Mini-project |")
    lines += [
        "",
        "Scores for open-ended work are partial by design. A reviewer (human or a configured model) "
        "must confirm full credit; Tuni'n does not claim to know a learner's mental state.",
        "",
    ]
    return "\n".join(lines)


def _sources(module: ModulePlan, proposal: CourseProposal) -> str:
    by_id = {s.id: s for s in proposal.sources}
    lines = [f"# Sources \u2014 {module.title}", ""]
    refs = [by_id[ref] for ref in module.evidence_refs if ref in by_id]
    if not refs:
        lines += [
            "_No source was attached to this module._ It is a plan-only study guide. Nothing in it "
            "should be read as a verified claim.",
            "",
        ]
    else:
        for source in refs:
            lines += [
                f"## [{source.title}]({source.url})",
                "",
                f"- Provider: `{source.provider or 'unknown'}`",
                f"- Type: `{source.source_type}`",
                f"- Retrieved: {source.retrieved_at}",
                f"- Relevance score: {source.relevance:g}",
                "",
            ]
            if source.snippet:
                lines += ["> " + source.snippet.replace("\n", " "), ""]
            lines += [
                "This source is a pointer, not an endorsement. Read it and record disagreement.",
                "",
            ]
    lines += [
        "## Research mode",
        "",
        f"`{proposal.research_mode.value}`",
        "",
        "## Limitations",
        "",
        *[f"- {limitation}" for limitation in proposal.limitations],
        "",
    ]
    return "\n".join(lines)


async def generate(module: ModulePlan, proposal: CourseProposal) -> list[ArtifactRecord]:
    """Write one module version and record every file. Idempotent per version."""
    errors = validate_module(module, proposal)
    if errors:
        raise ValueError("module failed artifact validation: " + "; ".join(errors))

    directory = module_dir(module)
    records: list[ArtifactRecord] = []

    def emit(kind: str, filename: str, content: str) -> None:
        path = directory / filename
        digest = _write(path, content)
        records.append(
            ArtifactRecord(
                course_id=module.course_id,
                module_id=module.id,
                kind=kind,
                path=str(path),
                version=module.version,
                content_hash=digest,
            )
        )

    emit("readme", "README.md", _readme(module, proposal))
    for index, lesson in enumerate(module.lessons, start=1):
        emit("lesson", _lesson_filename(index), lesson.content_md)
    emit("exercises", "exercises.md", _exercises(module))
    emit("answer_key", "answer_key.md", _answer_key(module))
    emit("rubric", "rubric.md", _rubric(module))
    emit("sources", "sources.md", _sources(module, proposal))
    emit(
        "metadata",
        "module.json",
        json.dumps(module.model_dump(mode="json"), ensure_ascii=False, indent=2),
    )

    for record in records:
        await store.add_artifact(record)
    module.artifact_dir = str(directory)
    return records


def read_artifact(path: str) -> Optional[str]:
    """Read a generated file, confined to the artifact root."""
    root = artifact_root().resolve()
    candidate = Path(path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate.read_text(encoding="utf-8")
