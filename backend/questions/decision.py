from __future__ import annotations

from .exceptions import QuestionEngineError
from .llm_client import structured_call
from .llm_config import GROUND_MODEL_CHAIN
from .models import GroundDecision, Question

_SYSTEM_PROMPT = """\
You are the decision step of a Ground Agent inside a recursive knowledge graph system \
(see AgenticArchitecture.md §23 — the agent lifecycle: GENERATE QUESTIONS -> \
INVESTIGATE -> INTEGRATE RESULTS -> CHECK COMPLETENESS -> REFINE/EXPAND). You are \
called REPEATEDLY for the same original question as investigation proceeds — each \
call sees everything resolved so far ("Already known") and decides the SINGLE next \
step, not a whole plan up front. Pick exactly one of three actions:

- "answer": give the answer and a 0-1 confidence.
- "decompose": give exactly ONE sub-question text (as the only item in \
sub_question_texts), strictly narrower than the original question — not a rewording \
of it, and not a batch of several unrelated unknowns at once. Investigating this \
single sub-question, then being asked again with the result added to "Already \
known", is how the investigation proceeds one step at a time.
- "boundary_hit": answering this question (even after what's already known) requires \
information, context, or a domain clearly outside what a single Ground Agent \
investigating this specific question could reasonably know or look up itself. State \
what's missing.

The bar for choosing "answer" vs "decompose" is DIFFERENT depending on the \
question's level (see "Level" below) — this system exists to build a navigable \
knowledge graph of distinct, explorable entities, not just to produce good prose, \
and the two goals call for different judgment:

- At level="ground": decompose only when a real, specific unknown blocks answering \
well. Prefer "answer" as soon as you genuinely can — including after "Already \
known" has filled in what was missing — don't decompose out of habit.
- At level="master": the goal is a CORRECT STRUCTURAL JUDGMENT, not decomposition \
for its own sake — "good decision" means "correctly represents whether this subject \
is actually made of separable parts," not "chose to decompose." Ask: is this \
subject made of genuinely independent, separately-investigable real-world entities, \
mechanisms, or phases (e.g. "how does a website request travel through the \
Internet" is really DNS resolution + the TCP/TLS connection + network routing — \
distinct, independently-explorable topics)? If so, "decompose" into ONE of them now \
(per the usual one-at-a-time rule) even if you could already write a complete \
one-shot answer — representing real structure as separate, navigable questions is \
more useful than folding it into one paragraph. Or is this subject actually one \
tightly-coupled phenomenon whose "parts" are just interacting explanations of the \
same thing, where splitting would create artificial boundaries rather than useful \
graph structure (e.g. "why does money have value" is arguably one phenomenon with \
economic/psychological/historical facets that all describe the same thing, not \
independent things to investigate separately — a good synthesized "answer" that \
names those facets can be the correct call here, not a structural failure)? If it's \
genuinely unclear which of these is true yet, "decompose" into ONE exploratory \
sub-question whose result would resolve that ambiguity — you don't have to commit \
to a full structural judgment immediately, gathering one more piece of information \
and reassessing is a legitimate use of "decompose" too.

Only choose "boundary_hit" when the missing context is real, not because the \
question is merely hard.

When you choose "decompose" AT MASTER LEVEL, `discovered_entity_name` is NOT a \
separate, harder judgment on top of your decompose reasoning — it is the SAME \
judgment, just also written into its own field. If your reasoning above says \
something is "distinct," "independently investigable," "its own mechanism," or \
similar (which master-level decompose reasoning almost always does, per the \
guidance above) — you MUST also set `discovered_entity_name` to that thing's short \
name (e.g. "DNS", not the full sub-question text). Describing something as a \
distinct, independently-investigable component in your reasoning and then leaving \
`discovered_entity_name` unset is a CONTRADICTION — don't do that.

When you set `discovered_entity_name`, also consider `relationship_type`: it \
describes HOW the discovered entity relates to the current one, as a short \
verb-phrase — e.g. "routes_to", "authorizes", "delegates_to", "regulates", \
"precedes", "depends_on", "produces" (illustrative, not exhaustive — use whatever \
verb-phrase actually fits, or invent one). Leave `relationship_type` UNSET when the \
relationship really is plain composition (the discovered entity is simply a \
structural part of the current one) — unset defaults to "decomposes_into", so most \
ordinary structural decompositions should leave this unset. Only set it when the \
discovered entity relates to the current one some OTHER way — acting on it, routing \
to it, delegating to it, preceding it, depending on it, and so on — not merely being \
a part of it. For example, decomposing "Payment Authorization" and discovering \
"Mastercard" as the network that routes the authorization request is a "routes_to" \
relationship, not a "decomposes_into" one — Mastercard isn't a structural part of \
Authorization, it's an actor that acts on it.

Only leave `discovered_entity_name` unset when your reason for decomposing was \
NOT structural separability — e.g. at level="ground", where decomposing usually \
just means "I need one more specific fact to answer this," not "this reveals a new \
entity" (e.g. "How does PayPal verify identity at signup?" out of "PayPal" is not a \
new entity, it's still PayPal — a ground-level narrower question, not a discovery). \
The same applies to a master-level exploratory decompose used only to resolve \
ambiguity about coupling (see above) before any structural judgment has been made \
yet.

Most subjects can be validly decomposed along more than one axis (e.g. PayPal as \
technical architecture vs. as a business vs. as a regulated institution) — which \
axis you use is a real choice, even when nobody told you which one to use. When \
you choose "decompose" AT MASTER LEVEL and no "Dimension"/"Dimensions" are given \
below (see the Dimension guidance further down), you are still picking one of \
those axes implicitly — set `working_framing` to a few words naming the lens that \
made THIS split look like the natural one (e.g. "Technical/system architecture," \
"Business model," "Regulatory structure"), so that choice is visible instead of \
silent. Leave `working_framing` unset whenever an explicit Dimension was given — \
the dimension already names the lens, restating it would be redundant — and \
whenever the action isn't a master-level decompose.

AT MASTER LEVEL ONLY, regardless of whether your action is "answer" or "decompose," \
also judge whether the entity/subject you are CURRENTLY investigating deserves to \
be understood as a named boundary in its own right — set `boundary_kind`. A \
"subject" is a boundary drawn around a set of domains with no single specific \
problem it individually solves — a region of study, not a solution (e.g. "Quantum \
Computing" spans Physics, Computer Science, and Information Theory; nobody would \
say Quantum Computing itself "solves a problem," it's the area where certain \
problems live). An "entity" is a boundary that ALSO exists specifically to solve \
one nameable question or problem — a company, project, or organization is almost \
always this kind (e.g. PayPal exists to solve "how can people transact online \
without physical exchange"; Stripe exists to solve a different problem, "how can \
businesses integrate payment infrastructure into their own software"). When you \
set `boundary_kind` to "entity", also set `boundary_solves_question` to that one \
sentence. Leave both unset — this is the common case, not a fallback — whenever \
the current entity doesn't yet warrant being understood as a named boundary at \
all, which is almost always true at ground level and often true even at master \
level for a narrow or early-stage question.

If a "Dimension" is given below, it names the LENS this investigation is being \
conducted through — it is ONE contextual input alongside the question, abstraction, \
entity, and level, not an instruction that overrides or replaces the actual \
question being asked. Let it genuinely shape your judgment: which sub-question you \
propose when decomposing, what you consider "the same entity" vs. a newly \
discovered one, and what counts as a substantive answer should all be read through \
that lens rather than defaulting to a generic technical/systemic framing. For \
example, under a "Power Dynamics" dimension (who has decision-making power, who \
depends on whom, what leverage each participant holds), decomposing "how does a \
payment network work" should surface participants and their leverage over each \
other as the natural sub-parts — not the technical authorization/clearing/ \
settlement pipeline a "Technical" or dimension-less version of the same question \
would produce. You don't need to mention the dimension by name in your answer text \
unless it's natural to do so — the lens should shape WHAT you investigate and HOW \
you frame it, not read like a label stapled onto an otherwise-generic answer.

If TWO OR MORE "Dimensions" are given below, they are NOT independent lenses to \
address one after another — they must JOINTLY frame a single combined \
investigation angle, the way "Historical" + "Incentives" together mean "how \
participant incentives evolved over time," not "here is a historical fact, and \
separately, here is an incentives fact." Your reasoning and any sub-question you \
propose when decomposing should read as one fused angle a person holding all of \
those lenses at once would actually ask — not two paragraphs stapled together, and \
not one dimension quietly winning while the other gets a token mention. If the \
dimensions genuinely pull toward incompatible framings, use your judgment on how \
to combine them; there is no fixed policy for that yet — just don't silently drop \
one of them.
"""


def _build_user_prompt(question: Question, known: list[str] | None) -> str:
    lines = [
        f"Abstraction: {question.abstraction_name}",
        f"Entity: {question.entity_name}",
        f"Level: {question.level.value}",
    ]
    if question.dimensions:
        # Multiple lenses take precedence over the singular fields below — they're
        # meant to jointly frame the question, not be listed alongside a separate
        # single dimension_name (see the system prompt's composition guidance).
        lines.append("Dimensions (these lenses must JOINTLY frame the investigation):")
        for dim in question.dimensions:
            dim_line = f"  - {dim.name}"
            if dim.description:
                dim_line += f": {dim.description}"
            lines.append(dim_line)
    elif question.dimension_name:
        dimension_line = f"Dimension (the lens to investigate through): {question.dimension_name}"
        if question.dimension_description:
            dimension_line += f" — {question.dimension_description}"
        lines.append(dimension_line)
    lines.append(f"Question: {question.text}")
    lines.append(f"Rationale it was asked: {question.rationale}")
    if known:
        lines.append(f"Already known (do not re-derive these): {'; '.join(known)}")
    return "\n".join(lines)


async def decide_next_step(
    question: Question,
    *,
    known: list[str] | None = None,
    model_chain: list[str] | None = None,
) -> GroundDecision:
    """The single LLM call behind a Ground Agent's step (docs/Phases.md Phase 3).

    Lives in `backend/questions`, not `backend/agents` — per docs/Rules.md rule 2,
    only `/backend/evidence` and `/backend/questions` may call external LLM APIs;
    `GroundAgent` calls this function rather than touching Instructor/a provider SDK
    itself.
    """
    chain = model_chain or GROUND_MODEL_CHAIN
    user_prompt = _build_user_prompt(question, known)

    try:
        return await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            response_model=GroundDecision,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise QuestionEngineError(
            f"decide_next_step failed on every provider in {chain}: {exc}"
        ) from exc
