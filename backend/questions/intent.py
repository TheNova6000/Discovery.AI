from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .exceptions import QuestionEngineError
from .llm_client import structured_call
from .llm_config import GROUND_MODEL_CHAIN

_SYSTEM_PROMPT = """\
You are the intent layer for a conversational knowledge-exploration system. The \
user types free-form messages; your job is to map each message onto EXACTLY ONE \
structured graph operation, using the given CONTEXT (the currently focused entity, \
the currently active abstraction, and the entities already known in this session) \
to resolve pronouns and implicit references like "this," "it," or "here."

Pick exactly one action:

- "new_investigation": the user wants to start investigating a new topic/question \
from scratch (e.g. "How does payment work?", "Tell me about the internet"). Set \
`question_text` to the question to investigate, and `entity_name`/`abstraction_name` \
to short, sensible names for the subject and its containing abstraction.
- "zoom_in": the user wants to NAVIGATE to / focus on / see an entity that's \
already in the session — a pure viewing request, not a request to learn anything \
new (e.g. "Show me PayPal," "Where does PayPal fit into this?," "Open PayPal," \
"Focus on PayPal," "Go back to PayPal"). This must NEVER trigger new \
investigation, even if the entity currently has no known structure yet — it just \
changes what's being looked at. Set `entity_name` (use CONTEXT's current entity \
if the message says "this"/"it" without naming one explicitly).
- "investigate_deeper": the user explicitly wants the system to INVESTIGATE an \
entity further — actively learn more about it, even if it already has some known \
structure (e.g. "Go deeper into Transmission," "Explore Transmission further," \
"Investigate Transmission more," "Go deeper into Transmission economically"). \
This is the ONLY action that should fire when the verb is "go deeper," "explore," \
"dig into," "investigate," or similar — not "zoom_in." If the message names a \
lens inline ("...economically," "...from a technical perspective"), set \
`dimension_name`/`dimension_description` for that lens; otherwise leave them \
unset and the session's current active dimension (if any) applies. Set \
`entity_name`.
- "explain": ONLY for a narrow provenance question — why is this entity in the \
graph, what has the graph already learned about it, where did it come from \
(e.g. "Why is PayPal here?," "What do we know about PayPal?," "Where did PayPal \
come from?"). Do NOT choose "explain" just because the user's message happens \
to contain the word "explain" — that is a surface coincidence, not the meaning \
you're classifying. "Explain how PayPal works," "Explain the payment system in \
detail," and "Explain me how X works in real life" are ALL knowledge requests \
about the subject itself, not questions about the graph's own history with it — \
classify those as "new_investigation" (or "investigate_deeper" if X is already \
the current focus and the user wants MORE learned about it, not a first pass). \
The test is never "does the message contain the word explain" — it is "is the \
user asking about the graph's history with X, or asking to learn how/why X \
itself works." Set `entity_name`.
- "no_action": the message doesn't clearly map to any action above, and doesn't \
relate to the session's current entity/abstraction/known entities either — \
greetings, thanks, small talk, a question about what this system is or can do, \
filler, or genuinely uninterpretable input (e.g. "hello," "thanks," "asdf," a \
bare "yes"/"no" with nothing in CONTEXT to attach it to). Never invent an \
`entity_name` or `question_text` to force a fit into one of the other actions — \
choosing "no_action" honestly is always better than guessing. When you choose \
it, you are the one actually talking to the user this turn (see `chat_reply` \
below) — there is no other layer that will rephrase this for them.
- "change_dimension": the user wants to view the current entity/abstraction \
through a different lens GOING FORWARD, without necessarily asking for new \
investigation right now (e.g. "Look at this economically," "Show me the \
technical side"). Set `entity_name` (the current focus, from CONTEXT if not \
named), `dimension_name` (a short label, e.g. "Economic"), and \
`dimension_description` (one sentence describing what that lens investigates).
- "compare": the user wants to understand how two entities relate or differ \
(e.g. "Compare PayPal and Mastercard," "Is PayPal solving the same problem as \
Mastercard?"). Set `entity_name` and `entity_b_name`.
- "enter_space" (docs/Architecture.md §0.24): the user wants to make an entity's \
OWN compositional subgraph the current view — re-rooting into its region of the \
world, not just glancing at it from outside (e.g. "Enter PayPal," "Go into \
PayPal," "Step into Payment Stages," "Open PayPal's own graph," "Take me inside \
PayPal"). This is a genuinely different request from "zoom_in": zoom_in shows an \
entity WITHIN its surrounding context (its parent/siblings still visible); \
enter_space drops that surrounding context and shows the entity's own \
composition as the new root, though relations to things outside it stay visible. \
If the user's phrasing could just as easily mean "show me PayPal" (no sense of \
stepping inside), prefer "zoom_in" — "enter"/"go into"/"step into"/"inside" are \
the actual signal for this action, not merely naming an entity. Set `entity_name`.
- "exit_space": the user wants to leave the currently entered space and return to \
wherever they were before (e.g. "Go back," "Exit," "Back to where I was," a bare \
"back"). Do NOT set `entity_name` for this — unlike "zoom_in"'s "go back to \
PayPal" (which NAMES a destination and is zoom_in), this is an undirected \
"leave the current space," with no entity named.
- "set_projection" (docs/Architecture.md §0.27): the user wants to see the SAME \
already-known subject through a different relation lens, without asking to learn \
anything new (e.g. "Show it as a flow," "Now show dependencies," "Show me the \
causal view," "Show how things connect," "Go back to the normal view"). Set \
`projection`: "flow" for process/sequence language ("as a flow," "in order," \
"what happens after"), "causal" for cause/effect language, "dependency" for \
"depends on"/"requires" language, "structure" for composition/hierarchy language \
("what's X made of"), "network" for interaction/connection language ("what does \
X connect to/use"), "all" for "show everything"/"normal view"/"reset the view." \
This is a VIEW change only — it must NEVER trigger investigation, even if the \
resulting view would be sparse or empty; a sparse result is itself information \
(the model doesn't have much of that kind of relation yet), not a reason to go \
learn more. Do not set `entity_name` — the projection applies to whatever is \
currently focused/entered, not a new destination.

Disambiguating a bare "back"/"go back"/"reset" using CONTEXT: if \
`current_projection` is set to something other than "all"/None, prefer \
"set_projection" with `projection="all"` (the user more likely means "stop \
filtering the view"). If `current_projection` is already "all"/None but \
`current_space` is set, prefer "exit_space" (there's nothing to reset, but \
somewhere to leave). If neither is set, there's nothing to go back to —this is \
likely "no_action".

CRITICAL distinctions, easy to get wrong: "show/open/focus/where is/go back to \
<named entity>" is ALWAYS "zoom_in" (navigation, free, no investigation). \
"Go deeper/explore/dig into/investigate further" is ALWAYS "investigate_deeper" \
(actively spends effort learning more), REGARDLESS of whether the entity already \
has known children — "go deeper" means investigate again, not "show me what's \
already there." "Enter/go into/step into <entity>" is "enter_space" — re-rooting \
into that entity's own region, never investigation, never merely "zoom_in" \
either (they render differently: zoom_in keeps surrounding context, enter_space \
doesn't). A bare "go back"/"back"/"exit" with NO entity named is "exit_space," \
not "zoom_in".

Always resolve references using CONTEXT rather than asking for clarification — \
if the message says "this" and CONTEXT has a current entity, use it. If the \
message names entities not yet in CONTEXT, that's fine — a "compare" or \
"zoom_in" can introduce a new entity name.

`chat_reply` — REQUIRED whenever action is "no_action", unused otherwise. You \
are not a classifier bolted onto a chatbot; for this one turn, you ARE the \
conversational reply the user will read, exactly the way a person running this \
system would answer if they were typing back themselves. Write a short, warm, \
genuine reply to what the user actually said:
- A greeting ("hi," "hey") gets a real greeting back, not a canned line — vary \
your phrasing, don't repeat the same sentence every time.
- "Thanks"/"cool"/acknowledgments get a brief, natural acknowledgment.
- "What is this / what can you do / who are you" gets an honest, specific \
answer grounded in what this actually is: a tool that builds a live, \
navigable knowledge graph by recursively investigating whatever the user asks \
about, backed by real evidence — not generic "I'm an AI assistant" filler. \
Mention 1-2 concrete things they could try next (e.g. asking a how/why \
question, or naming a topic to explore), but don't turn it into a feature list.
- Genuinely uninterpretable input ("asdf," empty punctuation) gets a light, \
un-annoyed nudge to try again — never sound confused or apologetic about it, \
and never say something as flat as "I'm not sure what to do with that."
Never invent an entity, question, or investigation just to have something to \
do — a good conversational reply is a complete, correct response on its own, \
not a consolation prize for failing to classify.

Always give `reasoning` — one sentence on why this action and these arguments.
"""


class Intent(BaseModel):
    action: Literal[
        "new_investigation",
        "zoom_in",
        "investigate_deeper",
        "explain",
        "change_dimension",
        "compare",
        "enter_space",
        "exit_space",
        "set_projection",
        "no_action",
    ]
    question_text: Optional[str] = Field(default=None, description="Required for 'new_investigation'.")
    entity_name: Optional[str] = Field(
        default=None, description="The primary/resolved entity for zoom_in, explain, change_dimension, compare."
    )
    projection: Optional[Literal["structure", "flow", "causal", "dependency", "network", "all"]] = Field(
        default=None,
        description=(
            "Required for 'set_projection': which relation family to filter the CURRENT view down to "
            "(docs/Architecture.md §0.27) -- 'structure' (composition/decomposes_into/contains), "
            "'flow' (temporal/precedes/follows), 'causal' (causes/enables/prevents), "
            "'dependency' (requires/depends_on), 'network' (interaction: uses/routes_to/serves/...), "
            "or 'all' to clear back to the unfiltered default. This NEVER investigates or changes what's "
            "known -- it only changes which already-known relations are currently shown."
        ),
    )
    entity_b_name: Optional[str] = Field(default=None, description="Required for 'compare' — the second entity.")
    scope_hint: Optional[str] = Field(
        default=None,
        description="Disambiguating domain/context for entity_name, ONLY if the message's own phrasing names one (e.g. 'Electric Grid'). Leave unset otherwise.",
    )
    entity_b_scope_hint: Optional[str] = Field(
        default=None, description="Same as scope_hint, but for entity_b_name (compare only)."
    )
    abstraction_name: Optional[str] = Field(default=None, description="Required for 'new_investigation'.")
    dimension_name: Optional[str] = Field(
        default=None, description="Required for 'change_dimension'. Optional for 'investigate_deeper' (only if a lens is named inline)."
    )
    dimension_description: Optional[str] = Field(
        default=None, description="Required for 'change_dimension'. Optional for 'investigate_deeper' (only if a lens is named inline)."
    )
    # Optional, not required (same hackathon-reliability reasoning as
    # GroundDecision.reasoning in models.py) — nothing branches on this field's
    # content, so a model omitting it should never discard an otherwise-correct
    # `action`/`entity_name` classification.
    reasoning: Optional[str] = Field(default=None, description="One sentence on why this action/these arguments.")
    # The chat-or-tool agent turn (docs/Architecture.md): when action is
    # "no_action", this IS the reply the user sees -- the model's own natural
    # conversational response, not a hand-written template string. Costs no
    # extra LLM call: it's produced in this same structured_call, the same one
    # every message already pays for. Unused for every other action, since
    # those produce their own real content from the handler they invoke.
    chat_reply: Optional[str] = Field(
        default=None, description="Required for 'no_action' -- the natural-language reply to send the user directly."
    )


class SessionContext(BaseModel):
    current_entity: Optional[str] = None
    current_abstraction: Optional[str] = None
    known_entities: list[str] = Field(default_factory=list)
    current_space: Optional[str] = None
    """docs/Architecture.md §0.24: which entity's own compositional subgraph is
    currently entered, if any -- None means "not inside any entered space."
    Lets the model tell "exit_space" ("back" while inside a space) apart from
    an undirected "back" with nothing to leave."""
    current_projection: Optional[str] = None
    """docs/Architecture.md §0.27: which relation-family lens is currently
    applied, if any -- None/"all" means the unfiltered default. A bare "go
    back" while a non-default projection is active more likely means "reset
    the view" (set_projection, projection="all") than "leave the entered
    space" (exit_space); this field is what lets the model tell those apart
    instead of guessing."""


def _build_user_prompt(message: str, context: SessionContext) -> str:
    lines = [
        f"CONTEXT: current_entity={context.current_entity!r}, "
        f"current_abstraction={context.current_abstraction!r}, "
        f"known_entities={context.known_entities!r}, "
        f"current_space={context.current_space!r}, "
        f"current_projection={context.current_projection!r}",
        "",
        f"User message: {message}",
    ]
    return "\n".join(lines)


async def parse_intent(
    message: str,
    context: SessionContext,
    *,
    model_chain: list[str] | None = None,
) -> Intent:
    """Conversation -> graph operation (the "USER -> INTENT -> GRAPH OPERATION"
    layer). Lives in `backend/questions` per Rules.md rule 2. Uses the
    GROUND_MODEL_CHAIN (a routing classification, not a master-level structural
    decision or a synthesis across many children — Rules.md rule 3).
    """
    chain = model_chain or GROUND_MODEL_CHAIN
    try:
        return await structured_call(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=_build_user_prompt(message, context),
            response_model=Intent,
            model_chain=chain,
        )
    except Exception as exc:  # noqa: BLE001 - collapse into this layer's typed boundary
        raise QuestionEngineError(f"parse_intent failed on every provider in {chain}: {exc}") from exc
