from __future__ import annotations

import os
import pathlib

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.agents import GroundAgent
from backend.graph import explain_entity, find_or_create_entity, get_decomposition
from backend.questions import Intent, Question, QuestionLevel, SessionContext, parse_intent

from .auth import get_current_user_id
from .session import ChatRequest, ChatResponse, SessionState, SwitchSessionRequest, get_store

app = FastAPI(title="Recursive Knowledge Graph — Demo")

# CORS_ORIGINS is a comma-separated allowlist (e.g. the Vercel frontend's URL)
# for the deployed split-origin setup; unset defaults to "*", matching the
# local/VM demo where frontend and backend are always same-origin anyway.
_cors_origins = os.environ.get("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",")] if _cors_origins != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend"

# Raised back from depth=1/steps=1 (docs/Memory.md — the Amazon investigation
# diagnosis): that cut was bundled with the real latency fix (routing
# master-level decisions to MASTER_MODEL_CHAIN) under time pressure, but it was
# the wrong lever — it silently discarded CORRECT decompose verdicts
# (decide_next_step reasoned AWS was a distinct, independently-investigable
# component and was overruled by the budget, not by its own judgment). The
# model-tier fix was the actual reliability win; this constant just has to be
# large enough for a genuinely broad question to finish decomposing before the
# budget kicks in. 2/3 matches what was actually verified working (steps=3
# still degrades to a fast single-child answer for narrow questions — the
# budget is a ceiling, not a target).
DEMO_MAX_DEPTH = 2
DEMO_MAX_STEPS = 3


async def _sync_decomposition(session: SessionState, entity_name: str) -> None:
    """Pull the real `decomposes_into` children Neo4j already has for this entity
    (written by `persist_to_graph=True`) into the session's fast in-memory graph
    mirror, so the live UI reflects genuinely discovered structure, not a guess.
    """
    entity = await find_or_create_entity(entity_name)
    children = await get_decomposition(entity.id)
    for child in children:
        session.add_edge(entity_name, child.name, "decomposes_into")


async def _run_investigation(session: SessionState, question: Question) -> str:
    agent = GroundAgent(question, persist_to_graph=True, max_depth=DEMO_MAX_DEPTH, max_sequential_steps=DEMO_MAX_STEPS)
    result = await agent.run()
    await _sync_decomposition(session, question.entity_name)
    session.current_entity = question.entity_name
    session.current_abstraction = question.abstraction_name
    return result.answer or f"Investigated {question.entity_name}, but no answer was produced."


async def handle_new_investigation(session: SessionState, intent: Intent) -> str:
    entity_name = intent.entity_name or (intent.question_text or "Subject").split("?")[0][:60]
    abstraction_name = intent.abstraction_name or "Exploration"
    question = Question(
        text=intent.question_text or f"How does {entity_name} work?",
        rationale="User-initiated investigation.",
        dimension_id=session.current_dimension_name or "none",
        dimension_name=session.current_dimension_name,
        dimension_description=session.current_dimension_description,
        level=QuestionLevel.MASTER,
        entity_name=entity_name,
        abstraction_name=abstraction_name,
    )
    session.add_node(abstraction_name, kind="abstraction")
    if abstraction_name != entity_name:
        # The intent parser occasionally names the abstraction the same as the
        # entity for broad topics ("Payments" for both) — a self-loop edge is
        # never meaningful, so just skip drawing one rather than rely on the
        # model always picking distinct names.
        session.add_edge(abstraction_name, entity_name, "contains")
    return await _run_investigation(session, question)


async def handle_zoom_in(session: SessionState, intent: Intent) -> str:
    """Pure navigation: focus on an entity and show whatever is already known
    about it. Deliberately NEVER triggers investigation, even when the entity
    has no known structure yet — "show/open/focus/go back to" must stay free
    (docs/Memory.md). "go deeper" is a different action (`investigate_deeper`)
    for exactly this reason; the two used to be conflated under one `zoom_in`
    handler that silently reused whatever stale structure already existed.
    """
    entity_name = intent.entity_name or session.current_entity
    if not entity_name:
        return "I don't have an entity in focus yet — ask a question first."

    entity = await find_or_create_entity(entity_name)
    await _sync_decomposition(session, entity_name)
    session.current_entity = entity_name
    children = await get_decomposition(entity.id)
    if not children:
        # No sub-components yet -- but don't claim "nothing investigated": the
        # entity may already have direct answers/claims attached (a leaf), just
        # no further decomposition. "explain" surfaces that provenance; this
        # message only speaks to structure, honestly.
        return f"Focused on {entity_name}. No further sub-components yet — try \"go deeper into {entity_name}\" to investigate it, or \"why is {entity_name} here\" to see what's already known about it."
    names = ", ".join(c.name for c in children)
    return f"Focused on {entity_name}. Known components: {names}."


async def handle_investigate_deeper(session: SessionState, intent: Intent) -> str:
    """Always runs a fresh investigation into the entity, regardless of whether
    it already has known children — "go deeper" is an imperative to investigate,
    not a request to see what's already there. An inline lens ("...economically")
    sets the session's active dimension going forward, same as `change_dimension`.
    """
    entity_name = intent.entity_name or session.current_entity
    if not entity_name:
        return "I don't have an entity in focus yet — ask a question first."

    dimension_name = intent.dimension_name or session.current_dimension_name
    dimension_description = intent.dimension_description or session.current_dimension_description
    if intent.dimension_name:
        session.current_dimension_name = intent.dimension_name
        session.current_dimension_description = intent.dimension_description

    lens_clause = f", specifically through a {dimension_name} lens" if dimension_name else ""
    question = Question(
        text=f"What are the key components or aspects of {entity_name}{lens_clause}?",
        rationale="User explicitly asked to investigate this entity further.",
        dimension_id=dimension_name or "none",
        dimension_name=dimension_name,
        dimension_description=dimension_description,
        level=QuestionLevel.MASTER,
        entity_name=entity_name,
        abstraction_name=session.current_abstraction or entity_name,
    )
    return await _run_investigation(session, question)


async def handle_explain(session: SessionState, intent: Intent) -> str:
    entity_name = intent.entity_name or session.current_entity
    if not entity_name:
        return "I don't have an entity in focus yet."
    # Make the entity visible in the live graph regardless of whether it turns
    # out to have any provenance yet — "explain" is a read, but the UI should
    # still reflect that this entity is now part of the conversation.
    session.add_node(entity_name)
    if session.current_entity and session.current_entity != entity_name:
        session.add_edge(session.current_entity, entity_name, "relates_to")
    entity = await find_or_create_entity(entity_name)
    explanation = await explain_entity(entity.id)
    if not explanation.discovered_by:
        return f"{entity_name} hasn't had any questions attached to it yet."
    lines = [f"{entity_name} was investigated via:"]
    for prov in explanation.discovered_by:
        lines.append(f"- {prov.question_text}")
    return "\n".join(lines)


async def handle_change_dimension(session: SessionState, intent: Intent) -> str:
    entity_name = intent.entity_name or session.current_entity
    if not entity_name:
        return "I don't have an entity in focus yet."
    session.current_dimension_name = intent.dimension_name
    session.current_dimension_description = intent.dimension_description
    question = Question(
        text=f"How does {entity_name} work, specifically viewed through a {intent.dimension_name} lens?",
        rationale=f"User asked to view {entity_name} through the {intent.dimension_name} dimension.",
        # Was the literal string "explicit" (a real bug, docs/Memory.md) —
        # destroyed the lens's identity, making it impossible to later tell
        # "this child was discovered under the Economic dimension" from "under
        # some other explicit dimension." Persist the actual name instead.
        dimension_id=intent.dimension_name,
        dimension_name=intent.dimension_name,
        dimension_description=intent.dimension_description,
        level=QuestionLevel.MASTER,
        entity_name=entity_name,
        abstraction_name=session.current_abstraction or entity_name,
    )
    return await _run_investigation(session, question)


async def handle_compare(session: SessionState, intent: Intent) -> str:
    a, b = intent.entity_name, intent.entity_b_name
    if not a or not b:
        return "I need two entities to compare."
    comparison_entity = f"{a} vs {b}"
    question = Question(
        text=f"What is the difference between {a} and {b}, and are they solving the same problem?",
        rationale="User asked to compare these two entities.",
        dimension_id=session.current_dimension_name or "none",
        dimension_name=session.current_dimension_name,
        dimension_description=session.current_dimension_description,
        level=QuestionLevel.MASTER,
        entity_name=comparison_entity,
        abstraction_name=session.current_abstraction or "Comparison",
    )
    session.add_edge(comparison_entity, a, "compares")
    session.add_edge(comparison_entity, b, "compares")
    return await _run_investigation(session, question)


_HANDLERS = {
    "new_investigation": handle_new_investigation,
    "zoom_in": handle_zoom_in,
    "investigate_deeper": handle_investigate_deeper,
    "explain": handle_explain,
    "change_dimension": handle_change_dimension,
    "compare": handle_compare,
}


@app.get("/graph")
async def get_graph(user_id: str = Depends(get_current_user_id)) -> dict:
    return get_store(user_id).current().to_payload()


@app.post("/reset")
async def reset(user_id: str = Depends(get_current_user_id)) -> dict:
    """Wipe the CURRENT session's graph/chat in place (same id, no new history
    entry) — for quick iteration/rehearsal, distinct from "New chat" below.
    """
    store = get_store(user_id)
    new_state = SessionState()
    new_state.session_id = store.current_id  # keep its place in history
    store.sessions[store.current_id] = new_state
    return new_state.to_payload()


@app.get("/sessions")
async def list_sessions(user_id: str = Depends(get_current_user_id)) -> list[dict]:
    return get_store(user_id).list_sessions()


@app.post("/sessions/new")
async def new_session(user_id: str = Depends(get_current_user_id)) -> dict:
    """The actual feature requested: reset the live graph for a new chat, while
    keeping every previous session in history rather than discarding it.
    """
    state = get_store(user_id).new_session()
    return state.to_payload()


@app.post("/sessions/switch")
async def switch_session(req: SwitchSessionRequest, user_id: str = Depends(get_current_user_id)) -> dict:
    try:
        state = get_store(user_id).switch(req.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No session with id {req.session_id!r}")
    return state.to_payload()


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user_id: str = Depends(get_current_user_id)) -> ChatResponse:
    session = get_store(user_id).current()
    session.add_message("user", req.message)
    context = SessionContext(
        current_entity=session.current_entity,
        current_abstraction=session.current_abstraction,
        known_entities=session.known_entities,
    )
    intent = await parse_intent(req.message, context)
    handler = _HANDLERS.get(intent.action)
    if handler is None:
        reply = f"I don't know how to handle intent: {intent.action}"
    else:
        try:
            reply = await handler(session, intent)
        except Exception as exc:  # noqa: BLE001 - surface to the demo UI instead of a 500
            reply = f"Something went wrong investigating that: {exc}"
    session.add_message("agent", reply, intent_action=intent.action)
    return ChatResponse(reply=reply, intent_action=intent.action, graph=session.to_payload())


# Serves the whole frontend/ directory (index.html landing page, app.html the
# actual tool) — html=True makes "/" resolve to index.html the same way static
# hosts like Vercel do. Registered LAST and deliberately: a mount at "/" would
# otherwise match every path as a prefix and swallow the API routes above it
# if it were registered first, since Starlette checks routes in registration
# order. This replaces the old single hardcoded FileResponse("/") route now
# that there's more than one page to serve.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
