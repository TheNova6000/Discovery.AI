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
- "explain": the user wants to know WHY an entity is where it is / what was \
learned about it (e.g. "Why is PayPal here?," "What do we know about PayPal?"). \
Set `entity_name`.
- "change_dimension": the user wants to view the current entity/abstraction \
through a different lens GOING FORWARD, without necessarily asking for new \
investigation right now (e.g. "Look at this economically," "Show me the \
technical side"). Set `entity_name` (the current focus, from CONTEXT if not \
named), `dimension_name` (a short label, e.g. "Economic"), and \
`dimension_description` (one sentence describing what that lens investigates).
- "compare": the user wants to understand how two entities relate or differ \
(e.g. "Compare PayPal and Mastercard," "Is PayPal solving the same problem as \
Mastercard?"). Set `entity_name` and `entity_b_name`.

CRITICAL distinction, easy to get wrong: "show/open/focus/where is/go back to" is \
ALWAYS "zoom_in" (navigation, free, no investigation). "Go deeper/explore/dig \
into/investigate further" is ALWAYS "investigate_deeper" (actively spends effort \
learning more), REGARDLESS of whether the entity already has known children — \
"go deeper" means investigate again, not "show me what's already there."

Always resolve references using CONTEXT rather than asking for clarification — \
if the message says "this" and CONTEXT has a current entity, use it. If the \
message names entities not yet in CONTEXT, that's fine — a "compare" or \
"zoom_in" can introduce a new entity name.

Always give `reasoning` — one sentence on why this action and these arguments.
"""


class Intent(BaseModel):
    action: Literal["new_investigation", "zoom_in", "investigate_deeper", "explain", "change_dimension", "compare"]
    question_text: Optional[str] = Field(default=None, description="Required for 'new_investigation'.")
    entity_name: Optional[str] = Field(
        default=None, description="The primary/resolved entity for zoom_in, explain, change_dimension, compare."
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


class SessionContext(BaseModel):
    current_entity: Optional[str] = None
    current_abstraction: Optional[str] = None
    known_entities: list[str] = Field(default_factory=list)


def _build_user_prompt(message: str, context: SessionContext) -> str:
    lines = [
        f"CONTEXT: current_entity={context.current_entity!r}, "
        f"current_abstraction={context.current_abstraction!r}, "
        f"known_entities={context.known_entities!r}",
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
