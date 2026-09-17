"""Dewey — the Learning Portal's own name and personified guide (docs/PRD.md
§9, docs/Architecture.md §0.83).

**Dewey is a separate module from Discovery.AI, on purpose, per an explicit
2026-09-17 restructuring decision.** Discovery.AI (`backend/graph`,
`backend/agents`, `backend/questions`, `backend/evidence`, `backend/reasoning`,
`backend/research`, `backend/research_api`) is the independent research/
reasoning engine — it investigates, retrieves evidence, forms claims, tracks
provenance, and exposes a stable `ResearchResponse`. It has no concept of
"Dewey" and never will; nothing in Discovery.AI imports from this package.

Dewey is the first real *client* of that engine (PRD.md §10.1's "Learning
Portal is the first client, not the place where the capability is built" —
now literally true at the package-import level, not just in prose): a
compiled course (`dewey.curriculum`) and a compiled, audited lesson
(`dewey.lessons`), each built by reading Discovery.AI's stable
`ResearchResponse` output and nothing else — no direct import of
`backend.graph`/`backend.agents`/`backend.reasoning` from anywhere in this
package (Rules.md rule 16's own restriction, now scoped to a whole module,
not just the Curriculum Compiler).

**The name.** Two real namesakes, both genuinely apt, not a coincidence
picked after the fact:
- The **Dewey Decimal System** — a library classifying and organizing
  knowledge for someone to find their way through it, the same job a
  compiled course does over Discovery.AI's own knowledge graph.
- **John Dewey**, the philosopher/psychologist whose educational theory —
  learning through real, guided experience rather than rote transmission —
  is the actual pedagogy this whole extension is built around: a lesson is
  composed from real investigated claims and audited for traceability
  (Rules.md rule 19), never asserted from an LLM's unsourced memory. Dewey
  the character teaches the way Dewey the philosopher argued teaching should
  work.

**The character.** Dewey is how a learner experiences this system — a warm,
curious, honest guide, not a faceless compiler. He never claims to know more
than the underlying research actually supports; when the evidence is thin,
he says so plainly rather than filling the gap (see
`dewey.lessons.compiler.compile_lesson`'s own `status="insufficient_claims"`
path, and `backend.questions.lesson_authoring`'s system prompt, which
composes explanations *in Dewey's voice* — encouraging, plain-spoken, never
condescending — while remaining just as strictly bound to only the real,
given claims). Doodle assets: `frontend/assets/dewey/`.
"""
