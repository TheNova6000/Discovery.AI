from __future__ import annotations

import uuid
from datetime import datetime, timezone

from backend.evidence import gather_evidence
from backend.graph import (
    attach_claim,
    attach_question,
    attach_relation_claim,
    create_relationship,
    find_or_create_entity,
    resolve_entity,
    set_boundary_kind,
)
from backend.questions import (
    GroundDecision,
    Question,
    QuestionLevel,
    canonicalize_relation,
    decide_next_step,
    extract_relations,
    is_relation_worthy,
    normalize_relationship_type,
    synthesize_answer,
)
from backend.questions.llm_config import MASTER_MODEL_CHAIN
from backend.runtime import init_db, load_state, save_state

from .bus import MessageBus
from .exceptions import AgentError
from .messages import BoundaryHitMessage
from .models import AgentState, AgentStatus, GroundResult

# Phase 3 has no MasterAgent yet to own a spawn budget (Rules.md rule 10 is a Phase 4
# concern). This is a local safety bound only, so a single Ground Agent's own
# recursion terminates instead of decomposing indefinitely.
DEFAULT_MAX_DEPTH = 2

# Refined post-Phase-5: decomposition is sequential/incremental (one sub-question
# investigated at a time, informed by what earlier ones found — see
# docs/Memory.md), not a single batch decided upfront. This caps how many
# sequential sub-questions ONE Ground Agent will pursue at its own level before
# being forced to conclude, independent of `max_depth` (which bounds recursion
# depth, not breadth/step count at a given level). Without this, a single agent
# could loop "investigate one more thing" indefinitely.
DEFAULT_MAX_SEQUENTIAL_STEPS = 4

# Per-process cache of db_paths whose schema has already been confirmed to exist,
# so `run()` doesn't re-run `CREATE TABLE IF NOT EXISTS` on every single recursive
# call — just once per (db_path) the first time any GroundAgent touches it. A
# Master (Phase 4) spawns many GroundAgents against the same db_path, so relying on
# every caller to remember to call `init_db()` first (Phase 3's convention, fine
# for one verify script) stopped being safe once spawning is no longer a single
# call site.
_initialized_db_paths: set[str] = set()


class GroundAgent:
    """A single node in a recursive Ground Agent tree (docs/Phases.md Phase 3).

    No separate `DomainAgent`/`SubdomainAgent` classes (Rules.md rule 8) — a Ground
    Agent that decides its question needs a sub-question spawns a child `GroundAgent`
    at depth+1, which is what a "Domain/Subdomain" layer functionally is in this
    design (AgenticArchitecture.md §3-8 "as implemented" note).

    Decomposition is sequential, not batched: each step investigates ONE
    sub-question, folds its result into "known", and re-decides — matching
    AgenticArchitecture.md §23's actual GENERATE -> INVESTIGATE -> INTEGRATE ->
    CHECK COMPLETENESS -> REFINE/EXPAND loop, rather than committing to a fixed set
    of sub-questions before any of them are answered.

    Every state transition is checkpointed to the SQLite state store before the
    next step runs (Rules.md rule 7), so `run()` doubles as the resume path:
    calling it again for the same `agent_id` from a fresh process picks up exactly
    where the last one left off — including mid-loop, re-deriving "known" from
    already-completed children — instead of re-deciding or re-spending LLM calls on
    already-settled work.
    """

    def __init__(
        self,
        question: Question,
        *,
        agent_id: str | None = None,
        parent_id: str | None = None,
        parent_chain: list[str] | None = None,
        depth: int = 0,
        max_depth: int = DEFAULT_MAX_DEPTH,
        max_sequential_steps: int = DEFAULT_MAX_SEQUENTIAL_STEPS,
        db_path: str | None = None,
        bus: MessageBus | None = None,
        gather_evidence: bool = False,
        persist_to_graph: bool = False,
    ) -> None:
        self.agent_id = agent_id or str(uuid.uuid4())
        self.parent_id = parent_id
        self.parent_chain = parent_chain or []  # root-first ancestor agent_ids
        self.question = question
        self.depth = depth
        self.max_depth = max_depth
        self.max_sequential_steps = max_sequential_steps
        self.db_path = db_path  # None -> state_store's own default path
        # Optional (docs/Phases.md Phase 4) — a Master's MessageBus this agent
        # posts BOUNDARY_HIT to. None means "run standalone" (Phase 3's usage),
        # which stays fully unchanged: no messages, no behavior difference.
        self.bus = bus
        # Opt-in (docs/Phases.md Phase 5), default False: real external retriever
        # API calls (and their rate limits/latency) only happen when explicitly
        # requested — Phase 3/4's behavior and free-tier API usage stay unaffected
        # for any existing caller that doesn't pass this.
        self.gather_evidence = gather_evidence
        # Opt-in (post-Phase-5 "recursive discovery -> entity resolution -> graph
        # persistence" pass, see docs/Memory.md): when true, every terminal
        # question this agent resolves gets attached to its (resolved-or-created)
        # canonical entity in Neo4j, and a "decompose" decision that discovers a
        # genuinely new entity creates that entity + a decomposes_into relationship
        # before the child even runs. Default False so Phase 3/4's behavior and
        # tests (which never touch Neo4j) are completely unaffected.
        self.persist_to_graph = persist_to_graph

    def _db_kwargs(self) -> dict:
        return {"db_path": self.db_path} if self.db_path else {}

    async def _load(self, agent_id: str) -> AgentState | None:
        raw = await load_state(agent_id, **self._db_kwargs())
        return AgentState.model_validate_json(raw) if raw else None

    async def _save(self, state: AgentState) -> None:
        state.updated_at = datetime.now(timezone.utc).isoformat()
        await save_state(state.agent_id, state.model_dump_json(), state.updated_at, **self._db_kwargs())

    async def _ensure_db(self) -> None:
        key = self.db_path or "__default__"
        if key not in _initialized_db_paths:
            await init_db(**self._db_kwargs())
            _initialized_db_paths.add(key)

    async def run(self) -> GroundResult:
        await self._ensure_db()
        existing = await self._load(self.agent_id)

        if existing is not None and existing.status in (
            AgentStatus.COMPLETE,
            AgentStatus.BOUNDARY_HIT,
            AgentStatus.FAILED,
        ):
            if existing.result is None:
                raise AgentError(
                    f"agent {self.agent_id} has terminal status {existing.status} "
                    "but no persisted result"
                )
            return existing.result

        # A fresh PENDING agent starts the loop with no children; a resumed
        # DECOMPOSING agent re-enters it with whatever children were already
        # spawned — both cases are handled by the same loop below.
        starting_children = list(existing.children) if existing is not None else []
        return await self._investigate_loop(starting_children)

    @staticmethod
    def _summarize_child(question_text: str, result: GroundResult) -> str:
        if result.status == AgentStatus.COMPLETE and result.answer:
            return f"Sub-question: {question_text}\nAnswer: {result.answer}"
        if result.status == AgentStatus.BOUNDARY_HIT:
            return f"Sub-question: {question_text}\nUnresolved (boundary hit): {result.boundary_reason}"
        return f"Sub-question: {question_text}\nNo answer available (status: {result.status.value})"

    def _make_child_question(self, text: str, *, entity_name: str | None = None) -> Question:
        return Question(
            text=text,
            rationale=f"Sub-question of: {self.question.text}",
            dimension_id=self.question.dimension_id,
            dimension_name=self.question.dimension_name,
            dimension_description=self.question.dimension_description,
            dimensions=self.question.dimensions,
            level=QuestionLevel.GROUND,
            entity_name=entity_name or self.question.entity_name,
            abstraction_name=self.question.abstraction_name,
        )

    async def _investigate_loop(self, children_ids: list[str]) -> GroundResult:
        # Catch up on any children already decided in a prior run (resume case) —
        # each child's own `run()` is itself resumable, so this replays cheaply
        # (zero LLM calls) for ones already COMPLETE/BOUNDARY_HIT.
        child_results: list[GroundResult] = []
        known: list[str] = []
        for child_id in children_ids:
            child_state = await self._load(child_id)
            if child_state is None:
                raise AgentError(
                    f"child {child_id} referenced by parent {self.agent_id} has no "
                    "persisted state"
                )
            child = GroundAgent(
                child_state.question,
                agent_id=child_id,
                parent_id=self.agent_id,
                parent_chain=[*self.parent_chain, self.agent_id],
                depth=child_state.depth,
                max_depth=self.max_depth,
                max_sequential_steps=self.max_sequential_steps,
                db_path=self.db_path,
                bus=self.bus,
                gather_evidence=self.gather_evidence,
                persist_to_graph=self.persist_to_graph,
            )
            result = await child.run()
            child_results.append(result)
            known.append(self._summarize_child(child_state.question.text, result))

        # docs/Architecture.md §0.21: a boundary-kind judgment is about the
        # CURRENT ENTITY's nature, not about any one decide_next_step call --
        # decide_next_step runs repeatedly for the same question as
        # decomposition proceeds, so this tracks the most recent non-empty
        # judgment across however many calls happen before _finish is
        # eventually reached, rather than only capturing whichever call
        # happens to be the terminal one.
        latest_boundary_kind: str | None = None
        latest_boundary_solves_question: str | None = None
        # docs/Architecture.md §0.22: every entity discovered while decomposing
        # THIS question (siblings under the same parent) — threaded into
        # extract_relations at _finish() so it can look for relations directly
        # between them, not just relations anchored on this entity alone.
        discovered_entity_names: list[str] = []

        while True:
            budget_exhausted = self.depth >= self.max_depth or len(children_ids) >= self.max_sequential_steps
            # Master-level structural decisions escalate to MASTER_MODEL_CHAIN
            # (Rules.md rule 3 already names this as a valid escalation reason;
            # this call site just never actually implemented it). Found live,
            # hackathon-day (docs/Memory.md): Groq's ground-tier model (gpt-oss-20b)
            # intermittently corrupts its own tool-call name specifically on
            # decompose decisions that also populate discovered_entity_name — a
            # master-level judgment by definition — while the larger master-tier
            # model (gpt-oss-120b) hasn't shown the same failure.
            step_model_chain = MASTER_MODEL_CHAIN if self.question.level == QuestionLevel.MASTER else None
            decision: GroundDecision = await decide_next_step(
                self.question, known=known or None, model_chain=step_model_chain
            )
            # Not persisted on GroundResult (no schema change) — printed so it's
            # visible in logs/eval output, since "why" a decision was made matters
            # for judging structural quality, not just what the decision was.
            framing_suffix = (
                f" working_framing={decision.working_framing!r}" if decision.working_framing else ""
            )
            print(
                f"[ground:{self.agent_id[:8]}] level={self.question.level.value} "
                f"action={decision.action} reasoning={decision.reasoning!r}{framing_suffix}"
            )
            if decision.boundary_kind:
                latest_boundary_kind = decision.boundary_kind
                latest_boundary_solves_question = decision.boundary_solves_question
                print(
                    f"[ground:{self.agent_id[:8]}] boundary_kind={decision.boundary_kind!r} "
                    f"solves_question={decision.boundary_solves_question!r}"
                )

            if decision.action == "answer":
                claims = await gather_evidence(self.question) if self.gather_evidence else []
                return await self._finish(
                    GroundResult(
                        status=AgentStatus.COMPLETE,
                        answer=decision.answer,
                        confidence=decision.confidence,
                        claims=claims,
                        child_results=child_results,
                    ),
                    children=children_ids,
                    boundary_kind=latest_boundary_kind,
                    boundary_solves_question=latest_boundary_solves_question,
                    sibling_entity_names=discovered_entity_names,
                )

            if decision.action == "decompose" and decision.sub_question_texts and not budget_exhausted:
                next_text = decision.sub_question_texts[0]
                child_entity_name = None
                if self.persist_to_graph and decision.discovered_entity_name:
                    # A genuinely new, reusable entity was discovered — not every
                    # sub-question implies one (see GroundDecision.discovered_entity_name
                    # and decision.py's prompt). Resolve-or-create BOTH ends before
                    # creating the relationship, and attach the child question to the
                    # NEW entity, not the parent's — this is what makes the graph
                    # actually remember the discovery instead of just accumulating
                    # narrower questions under one node.
                    # scope_hint on the PARENT lookup only (Pass 3, docs/Architecture.md
                    # §0.14): without it, this call could resolve to a different,
                    # wrong same-named node than the one _finish() below resolves for
                    # the same question — the exact identity bug this pass exists to
                    # prevent. The newly-discovered child has no scope of its own yet
                    # from this mechanism; deliberately out of scope for Pass 3's
                    # narrow acceptance test (top-level entity resolution only).
                    parent_entity = await find_or_create_entity(
                        self.question.entity_name, scope_hint=self.question.entity_scope_hint
                    )
                    child_entity = await find_or_create_entity(decision.discovered_entity_name)
                    # docs/Architecture.md §0.17: relationship_type is the LLM's own
                    # word for how the child relates to the parent (e.g. "routes_to",
                    # "delegates_to") — unset falls back to the old default so every
                    # existing call site keeps producing exactly today's behavior.
                    # create_relationship already accepted any relationship_type
                    # string; this was the only call site, and it was hardcoded.
                    relationship_type = decision.relationship_type or "decomposes_into"
                    await create_relationship(parent_entity.id, child_entity.id, relationship_type)
                    # docs/Architecture.md §0.26: a structural/decompose relation's
                    # "evidence" is the agent's own reasoning for the split, not an
                    # external citation -- a genuinely different provenance kind
                    # than extract_relations' sourced claims below, given a lower
                    # baseline confidence (0.6) to reflect that honestly rather
                    # than treating a reasoning-based judgment as equally certain
                    # as independently corroborated evidence. Never fatal: this is
                    # enrichment, same tolerance as every other _finish()-adjacent
                    # persistence step in this file.
                    try:
                        await attach_relation_claim(
                            parent_entity.id,
                            child_entity.id,
                            relationship_type,
                            claim_id=str(uuid.uuid4()),
                            evidence=decision.reasoning or f"Decomposed while investigating {self.question.entity_name}.",
                            reasoning="Master-level structural decomposition judgment, not sourced evidence.",
                            confidence=0.6,
                            source_title="Agent reasoning",
                            source_url="",
                            source_type="reasoning",
                            valid_from=datetime.now(timezone.utc).isoformat(),
                        )
                    except Exception as exc:  # noqa: BLE001 - enrichment, must not break decompose
                        print(f"[relations] attach_relation_claim (decompose) failed, degrading silently: {exc}")
                    child_entity_name = decision.discovered_entity_name
                    discovered_entity_names.append(decision.discovered_entity_name)
                    print(
                        f"[graph] {parent_entity.name!r} -[{relationship_type}]-> {child_entity.name!r}"
                    )

                child_id = str(uuid.uuid4())
                child_question = self._make_child_question(next_text, entity_name=child_entity_name)

                # Child checkpointed, then the parent's growing children list, BEFORE
                # running the child — same crash-safety ordering as the original
                # batch design: if the process dies right after this save, resume
                # finds a DECOMPOSING parent whose children list only ever points at
                # agent_ids that were actually persisted.
                await self._save(
                    AgentState(
                        agent_id=child_id,
                        parent_id=self.agent_id,
                        question=child_question,
                        depth=self.depth + 1,
                        max_depth=self.max_depth,
                        status=AgentStatus.PENDING,
                    )
                )
                children_ids = [*children_ids, child_id]
                await self._save(
                    AgentState(
                        agent_id=self.agent_id,
                        parent_id=self.parent_id,
                        question=self.question,
                        depth=self.depth,
                        max_depth=self.max_depth,
                        status=AgentStatus.DECOMPOSING,
                        children=children_ids,
                    )
                )

                child = GroundAgent(
                    child_question,
                    agent_id=child_id,
                    parent_id=self.agent_id,
                    parent_chain=[*self.parent_chain, self.agent_id],
                    depth=self.depth + 1,
                    max_depth=self.max_depth,
                    max_sequential_steps=self.max_sequential_steps,
                    db_path=self.db_path,
                    bus=self.bus,
                    gather_evidence=self.gather_evidence,
                    persist_to_graph=self.persist_to_graph,
                )
                result = await child.run()
                child_results.append(result)
                known.append(self._summarize_child(next_text, result))
                continue

            # Either a direct boundary hit, or "decompose" requested with the
            # depth/step budget exhausted (AgenticArchitecture.md §10-11's
            # "abstraction too deep for current objective" is exactly this
            # condition).
            #
            # Observed live (2026-08-27 known-answer eval): the model sometimes
            # fills `boundary_reason` with the literal string "null" instead of
            # leaving it unset or giving a real reason — a falsy-string check
            # alone doesn't catch that, so it's matched explicitly.
            given_reason = (decision.boundary_reason or "").strip()
            reason = (
                given_reason
                if given_reason and given_reason.lower() != "null"
                else f"depth/step limit reached while question still needed decomposition"
            )

            if child_results:
                # Partial investigation already happened — synthesize the best
                # answer available from what WAS resolved rather than discarding
                # it for a bare, contentless boundary hit.
                synthesis = await synthesize_answer(self.question, known)
                return await self._finish(
                    GroundResult(
                        status=AgentStatus.COMPLETE,
                        answer=synthesis.answer,
                        confidence=synthesis.confidence,
                        child_results=child_results,
                    ),
                    children=children_ids,
                    boundary_kind=latest_boundary_kind,
                    boundary_solves_question=latest_boundary_solves_question,
                    sibling_entity_names=discovered_entity_names,
                )

            return await self._finish(
                GroundResult(status=AgentStatus.BOUNDARY_HIT, boundary_reason=reason),
                boundary_kind=latest_boundary_kind,
                boundary_solves_question=latest_boundary_solves_question,
            )

    async def _finish(
        self,
        result: GroundResult,
        *,
        children: list[str] | None = None,
        boundary_kind: str | None = None,
        boundary_solves_question: str | None = None,
        sibling_entity_names: list[str] | None = None,
    ) -> GroundResult:
        await self._save(
            AgentState(
                agent_id=self.agent_id,
                parent_id=self.parent_id,
                question=self.question,
                depth=self.depth,
                max_depth=self.max_depth,
                status=result.status,
                children=children or [],
                result=result,
            )
        )
        if self.persist_to_graph:
            # Single choke point for every terminal outcome (answered directly,
            # synthesized from children, or boundary-hit) — the graph remembers
            # every question this agent resolved, not just the ones that got a
            # direct answer. Idempotent: `find_or_create_entity` and `attach_*`
            # both MERGE, so resuming a crashed run never creates duplicates.
            entity = await find_or_create_entity(
                self.question.entity_name, scope_hint=self.question.entity_scope_hint
            )
            if boundary_kind:
                # docs/Architecture.md §0.21: recorded separately from the
                # decompose/answer decision itself -- a boundary-kind judgment
                # can accompany either action, and isn't required for either.
                try:
                    await set_boundary_kind(
                        entity.id, boundary_kind=boundary_kind, solves_question=boundary_solves_question
                    )
                    print(f"[graph] {entity.name!r} boundary_kind={boundary_kind!r}")
                except Exception as exc:  # noqa: BLE001 - enrichment, must not break _finish
                    print(f"[boundary_kind] set_boundary_kind failed, degrading silently: {exc}")
            await attach_question(
                entity.id,
                question_id=self.question.id,
                text=self.question.text,
                dimension_id=self.question.dimension_id,
                level=self.question.level.value,
                rationale=self.question.rationale,
            )
            for claim in result.claims:
                await attach_claim(
                    self.question.id,
                    claim_id=claim.id,
                    evidence=claim.evidence,
                    reasoning=claim.reasoning,
                    confidence=claim.confidence,
                    source_title=claim.source.title,
                    source_url=claim.source.url,
                    source_type=claim.source.source_type,
                    valid_from=claim.valid_from,
                )
            if result.answer:
                # docs/Architecture.md §0.18: a genuinely separate decision from
                # decide_next_step's decompose branch above — extract_relations is
                # never asked to "decompose" anything, which is what made the
                # difference in the controlled experiment (the IDS/Privilege
                # Escalation case: the same content, asked inside a "decompose"
                # framing, produced decomposes_into; asked as its own decision, it
                # produced the correct "spots" actor relation). Degrades to zero
                # relations on total provider failure, same tolerance as
                # gather_evidence's retrievers — an enrichment step failing must
                # never take down the answer it was enriching. docs/Architecture.md
                # §0.22: also passes every sibling entity discovered while
                # decomposing this question, so extraction can find relations
                # directly between them (e.g. Client Bank -> Merchant Bank) instead
                # of only ever radiating from this one entity — the documented fix
                # for LLM extraction's bias toward the named "topic" entity.
                try:
                    candidates = await extract_relations(
                        self.question.entity_name,
                        result.answer,
                        sibling_entity_names=sibling_entity_names,
                    )
                except Exception as exc:  # noqa: BLE001 - enrichment, must not break _finish
                    print(f"[relations] extract_relations failed, degrading to zero results: {exc}")
                    candidates = []
                for candidate in candidates:
                    if not is_relation_worthy(candidate):
                        continue
                    # docs/Architecture.md §0.18: canonicalization is a separate step
                    # from extraction, verified 8/8 on an adversarial active/passive/
                    # modal matrix to collapse surface-voice variation onto the same
                    # source/target/direction without inventing content. Falls back to
                    # the raw (already-worthy) candidate on total provider failure --
                    # canonicalization improves representation, it was never required
                    # for the relation to be true.
                    try:
                        canonical = await canonicalize_relation(candidate)
                        source_name, relationship_type, target_name = (
                            canonical.canonical_source,
                            canonical.canonical_relationship_type,
                            canonical.canonical_target,
                        )
                    except Exception as exc:  # noqa: BLE001 - enrichment, must not break _finish
                        print(f"[relations] canonicalize_relation failed, using raw candidate: {exc}")
                        source_name, relationship_type, target_name = (
                            candidate.source_entity,
                            candidate.relationship_type,
                            candidate.target_entity,
                        )
                    relationship_type = normalize_relationship_type(relationship_type)
                    # docs/Architecture.md §0.18: resolve_entity, not find_or_create_entity
                    # — frozen after a 6-case evidence-type matrix (all correct) proved
                    # deterministic candidate resolution can distinguish REUSE / CREATE /
                    # AMBIGUOUS / CONFLICT without an LLM. A relation is only persisted
                    # when BOTH endpoints resolve to something acceptable — an unresolved
                    # endpoint must never pollute the world model with a half-known edge.
                    source_resolution = await resolve_entity(
                        source_name, candidate.justification, scope_hint=self.question.entity_scope_hint
                    )
                    target_resolution = await resolve_entity(
                        target_name, candidate.justification, scope_hint=self.question.entity_scope_hint
                    )
                    if source_resolution.decision not in ("REUSE", "CREATE") or target_resolution.decision not in (
                        "REUSE",
                        "CREATE",
                    ):
                        print(
                            f"[relations] skipped {source_name!r} -[{relationship_type}]-> {target_name!r}: "
                            f"source={source_resolution.decision} ({source_resolution.reason}), "
                            f"target={target_resolution.decision} ({target_resolution.reason})"
                        )
                        continue
                    source_entity = source_resolution.selected_node
                    target_entity = target_resolution.selected_node
                    await create_relationship(source_entity.id, target_entity.id, relationship_type)
                    print(
                        f"[relations] {source_entity.name!r} -[{relationship_type}]-> "
                        f"{target_entity.name!r}"
                    )
                    # docs/Architecture.md §0.26: `candidate.justification` was
                    # already being computed (used above for resolve_entity's own
                    # context) and then discarded once the edge was written --
                    # attached here as real evidence instead, under this exact
                    # relation identity (source, relationship_type, target). Five
                    # independent discoveries of the same relation now accumulate
                    # as five claims, not five identical printed log lines.
                    # Confidence is a fixed baseline (0.7, higher than a
                    # structural decompose judgment's 0.6 above, since this is
                    # text-sourced rather than pure agent reasoning) -- not
                    # LLM-self-reported, deliberately: adding a confidence field
                    # to CandidateRelation's own schema would reopen exactly the
                    # schema-flakiness class of failure just stabilized this
                    # session (docs/Memory.md).
                    try:
                        await attach_relation_claim(
                            source_entity.id,
                            target_entity.id,
                            relationship_type,
                            claim_id=str(uuid.uuid4()),
                            evidence=candidate.justification or "No justification text was extracted.",
                            reasoning=f"Extracted while investigating {self.question.entity_name}.",
                            confidence=0.7,
                            source_title="Extracted from investigation text",
                            source_url="",
                            source_type="extraction",
                            valid_from=datetime.now(timezone.utc).isoformat(),
                        )
                    except Exception as exc:  # noqa: BLE001 - enrichment, must not break _finish
                        print(f"[relations] attach_relation_claim failed, degrading silently: {exc}")
        if self.bus is not None and result.status == AgentStatus.BOUNDARY_HIT:
            # Escalation (Rules.md rule 5) — never skipped or short-circuited: a
            # boundary hit is always posted to the bus when one exists, regardless
            # of depth in the tree. `parent_chain` records how it propagated up;
            # the Master (the bus's only consumer) is where it actually lands.
            await self.bus.send(
                BoundaryHitMessage(
                    sender_id=self.agent_id,
                    parent_chain=self.parent_chain,
                    question_text=self.question.text,
                    reason=result.boundary_reason or "unspecified",
                )
            )
        return result
