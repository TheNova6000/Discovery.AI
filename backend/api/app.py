from __future__ import annotations

import os
import pathlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.agents import GroundAgent
from backend.graph import (
    explain_entity,
    find_or_create_entity,
    get_claims_for_question,
    get_decomposition,
    get_questions_for_entity,
)
from backend.questions import Intent, Question, QuestionLevel, SessionContext, parse_intent
from backend.questions.llm_config import set_current_user_keys

from . import db
from .auth import get_current_user_id
from .session import (
    ChatRequest,
    ChatResponse,
    PendingAction,
    SessionState,
    SettingsUpdateRequest,
    SwitchSessionRequest,
    get_store,
    persist,
)

app = FastAPI(title="Recursive Knowledge Graph — Demo")


@app.on_event("startup")
async def _startup() -> None:
    await db.init_pool()

# CORS_ORIGINS is a comma-separated allowlist (e.g. the Vercel frontend's URL)
# for the deployed split-origin setup; unset defaults to "*", matching the
# local/VM demo where frontend and backend are always same-origin anyway.
_cors_origins = os.environ.get("CORS_ORIGINS", "*")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _cors_origins.split(",")] if _cors_origins != "*" else ["*"],
    # allow_credentials=True + allow_origins=["*"] is a real, recurring bug, not
    # a hypothetical one — browsers refuse a wildcard Access-Control-Allow-Origin
    # paired with Access-Control-Allow-Credentials: true (confirmed live: the
    # production frontend's every /chat call failed with exactly this CORS
    # rejection). This app has no reason to need it: auth is a Bearer token
    # attached explicitly via the Authorization header (authHeaders() in
    # chat.html), never a browser-managed cookie -- credentialed CORS mode
    # exists for cookies/TLS-client-certs, not manually-set headers, so it was
    # never actually required here. False works with CORS_ORIGINS unset (the
    # local/VM demo) and with it set (the real deployment) alike.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = pathlib.Path(__file__).resolve().parent.parent.parent / "frontend"

# Bring-your-own-key settings: same in-memory-cache-in-front-of-Postgres shape
# as SessionStore/get_store in session.py (fast after the first request per
# process, correct fallback to Postgres on a cold start, correct fallback to
# pure in-memory when DATABASE_URL isn't set at all -- the VM/local demo).
_USER_KEYS_CACHE: dict[str, dict] = {}
_SETTINGS_FIELDS = ("groq_api_key", "gemini_api_key", "cerebras_api_key", "cohere_api_key")


async def _get_user_keys(user_id: str) -> dict:
    if user_id in _USER_KEYS_CACHE:
        return _USER_KEYS_CACHE[user_id]
    keys = await db.fetch_user_keys(user_id) or {}
    _USER_KEYS_CACHE[user_id] = keys
    return keys


async def _save_user_keys(user_id: str, updates: SettingsUpdateRequest) -> dict:
    current = await _get_user_keys(user_id)
    merged = dict(current)
    for field in _SETTINGS_FIELDS:
        value = getattr(updates, field)
        if value is not None:
            merged[field] = value or None  # explicit "" clears back to the shared server pool
    _USER_KEYS_CACHE[user_id] = merged
    await db.upsert_user_keys(user_id, merged)
    return merged


def _settings_status(keys: dict) -> dict:
    return {f"{field}_set": bool(keys.get(field)) for field in _SETTINGS_FIELDS}


def _resolve_provider_keys(stored: dict) -> dict[str, str]:
    """Maps this project's settings field names onto the provider-prefix names
    `structured_call` actually keys its lookups by (see llm_config.py) --
    cohere_api_key is intentionally not mapped to anything: Cohere isn't in
    either active model chain (dropped, docs/Memory.md), so a saved Cohere key
    currently has no effect on any real call. Kept in settings anyway since
    it's one of the four keys this project already asks users to manage.
    """
    resolved: dict[str, str] = {}
    if stored.get("groq_api_key"):
        resolved["groq"] = stored["groq_api_key"]
    if stored.get("gemini_api_key"):
        resolved["google"] = stored["gemini_api_key"]
    if stored.get("cerebras_api_key"):
        resolved["cerebras"] = stored["cerebras_api_key"]
    return resolved


@app.get("/settings")
async def get_settings(user_id: str = Depends(get_current_user_id)) -> dict:
    return _settings_status(await _get_user_keys(user_id))


@app.post("/settings")
async def update_settings(req: SettingsUpdateRequest, user_id: str = Depends(get_current_user_id)) -> dict:
    return _settings_status(await _save_user_keys(user_id, req))

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


async def _sync_decomposition(session: SessionState, entity_name: str, scope_hint: str | None = None) -> None:
    """Pull the real `decomposes_into` children Neo4j already has for this entity
    (written by `persist_to_graph=True`) into the session's fast in-memory graph
    mirror, so the live UI reflects genuinely discovered structure, not a guess.

    `scope_hint` (Pass 3, docs/Architecture.md §0.14): without it, this call could
    resolve to a different same-named node than the one the investigation itself
    just used — the session's displayed graph would look wrong even though Neo4j
    is correct, exactly the kind of false negative Pass 3's acceptance test needs
    to rule out.
    """
    entity = await find_or_create_entity(entity_name, scope_hint=scope_hint)
    children = await get_decomposition(entity.id)
    for child in children:
        session.add_edge(entity_name, child.name, "decomposes_into")


async def _run_investigation(session: SessionState, question: Question) -> str:
    agent = GroundAgent(
        question,
        persist_to_graph=True,
        gather_evidence=True,
        max_depth=DEMO_MAX_DEPTH,
        max_sequential_steps=DEMO_MAX_STEPS,
    )
    result = await agent.run()
    await _sync_decomposition(session, question.entity_name, question.entity_scope_hint)
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
        entity_scope_hint=intent.scope_hint,
        abstraction_name=abstraction_name,
    )
    # Graph annotation happens AFTER a successful investigation, not before --
    # confirmed live (2026-08-29) that adding these unconditionally up front
    # left a visible entity/abstraction node in the graph even when
    # `_run_investigation` raised (e.g. every provider quota-exhausted), while
    # the chat reply was just the same generic error string every retry. That
    # made "Regenerate" look like it was silently doing SOMETHING (the graph
    # changed) while the actual answer never did.
    answer = await _run_investigation(session, question)
    session.add_node(abstraction_name, kind="abstraction")
    if abstraction_name != entity_name:
        # The intent parser occasionally names the abstraction the same as the
        # entity for broad topics ("Payments" for both) — a self-loop edge is
        # never meaningful, so just skip drawing one rather than rely on the
        # model always picking distinct names.
        session.add_edge(abstraction_name, entity_name, "contains")
    return answer


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

    entity = await find_or_create_entity(entity_name, scope_hint=intent.scope_hint)
    await _sync_decomposition(session, entity_name, intent.scope_hint)
    session.current_entity = entity_name
    children = await get_decomposition(entity.id)
    if not children:
        # docs/Architecture.md §0.20: same fix as handle_explain -- don't just
        # report the dead end and require the user to type the exact right
        # follow-up phrase. zoom_in still never investigates ON ITS OWN (that
        # stays deliberate -- navigation stays free); it now offers to, via the
        # same PendingAction mechanism, so a plain "yes" works. "why is X here"
        # stays mentioned as a distinct alternative (provenance, not
        # investigation) that a bare confirmation can't cover.
        session.pending_action = PendingAction(
            action="investigate_deeper",
            entity_name=entity_name,
            scope_hint=intent.scope_hint,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return f"Focused on {entity_name}. No further sub-components yet — want me to go deeper into it? (Or ask \"why is {entity_name} here\" to see what's already known about it.)"
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
        entity_scope_hint=intent.scope_hint,
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
    session.current_entity = entity_name  # docs/Architecture.md §0.20, root cause C:
    # every other handler that resolves a focal entity (zoom_in, investigate_deeper)
    # sets this; explain silently didn't, so a follow-up "why?"/"go deeper"/"yes"
    # had no reliable focus to resolve against.
    entity = await find_or_create_entity(entity_name, scope_hint=intent.scope_hint)
    explanation = await explain_entity(entity.id)
    if not explanation.discovered_by:
        # docs/Architecture.md §0.20: don't dead-end on "no questions attached" --
        # offer to investigate, as a structured PendingAction so a follow-up
        # "yes" resolves deterministically (see _classify_confirmation) instead
        # of being handed to parse_intent, which — confirmed live — will
        # fabricate a full new_investigation out of a bare "yes" rather than
        # admit it has nothing to go on.
        session.pending_action = PendingAction(
            action="new_investigation",
            entity_name=entity_name,
            question_text=f"How does {entity_name} work?",
            scope_hint=intent.scope_hint,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        return f"{entity_name} hasn't been investigated yet — want me to look into it?"
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
        entity_scope_hint=intent.scope_hint,
        abstraction_name=session.current_abstraction or entity_name,
    )
    return await _run_investigation(session, question)


async def handle_compare(session: SessionState, intent: Intent) -> str:
    a, b = intent.entity_name, intent.entity_b_name
    if not a or not b:
        return "I need two entities to compare."
    # Pass 3 (docs/Architecture.md §0.14): resolve both sides against their
    # respective scoped identities BEFORE building the comparison, so "compare"
    # retrieves the two distinct canonical nodes an earlier scoped investigation
    # already created, instead of the comparison being purely a display-layer
    # label with no real Neo4j-level resolution behind either side.
    entity_a = await find_or_create_entity(a, scope_hint=intent.scope_hint)
    entity_b = await find_or_create_entity(b, scope_hint=intent.entity_b_scope_hint)
    print(f"[compare] resolved {a!r} (scope={intent.scope_hint!r}) -> node {entity_a.id}")
    print(f"[compare] resolved {b!r} (scope={intent.entity_b_scope_hint!r}) -> node {entity_b.id}")
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
    # Same fix as handle_new_investigation above: don't draw the comparison
    # edges until the investigation actually succeeds.
    answer = await _run_investigation(session, question)
    session.add_edge(comparison_entity, a, "compares")
    session.add_edge(comparison_entity, b, "compares")
    return answer


async def handle_no_action(session: SessionState, intent: Intent) -> str:
    """docs/Architecture.md §0.20: the classifier's escape hatch — chosen when a
    message doesn't clearly map to any real action and doesn't relate to session
    context. Exists so short/uninterpretable input never forces the model to
    invent an entity_name or question_text just to produce SOME action.
    """
    return "I'm not sure what to do with that — could you rephrase, or tell me what you'd like to explore?"


_HANDLERS = {
    "new_investigation": handle_new_investigation,
    "zoom_in": handle_zoom_in,
    "investigate_deeper": handle_investigate_deeper,
    "explain": handle_explain,
    "change_dimension": handle_change_dimension,
    "compare": handle_compare,
    "no_action": handle_no_action,
}


# docs/Architecture.md §0.20: a small, deterministic, non-LLM classifier for
# yes/no-shaped replies -- built from variants actually worth covering, same
# "start small, extend only on observed need" discipline as
# normalize_relationship_type's synonym table, not an attempt at general NLP.
# Runs on EVERY turn before parse_intent ever sees the message: a bare
# confirmation must never reach the LLM, because it has nothing to interpret
# "yes" against except whatever thin session context happens to be lying
# around -- confirmed live to fabricate a full new_investigation from it.
_AFFIRMATIVE = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "do it", "go ahead",
    "please do", "sounds good", "go for it", "please",
}
_NEGATIVE = {
    "no", "nope", "nah", "don't", "dont", "skip", "cancel", "not now",
    "no thanks", "never mind", "nevermind",
}


def _classify_confirmation(message: str) -> Optional[bool]:
    normalized = message.strip().lower().rstrip(".!?")
    if normalized in _AFFIRMATIVE:
        return True
    if normalized in _NEGATIVE:
        return False
    return None


async def _execute_pending_action(session: SessionState, pending: PendingAction) -> str:
    """Reuses the exact same handler a fresh Intent would have gone through --
    no separate logic to keep in sync -- by building a synthetic Intent from the
    structured PendingAction instead of from an LLM guess.
    """
    synthetic_intent = Intent(
        action=pending.action,
        question_text=pending.question_text,
        entity_name=pending.entity_name,
        abstraction_name=pending.entity_name,
        scope_hint=pending.scope_hint,
        dimension_name=pending.dimension_name,
        dimension_description=pending.dimension_description,
    )
    handler = _HANDLERS[pending.action]
    return await handler(session, synthetic_intent)


@app.get("/graph")
async def get_graph(user_id: str = Depends(get_current_user_id)) -> dict:
    store = await get_store(user_id)
    return store.current().to_payload()


@app.post("/reset")
async def reset(user_id: str = Depends(get_current_user_id)) -> dict:
    """Wipe the CURRENT session's graph/chat in place (same id, no new history
    entry) — for quick iteration/rehearsal, distinct from "New chat" below.
    """
    store = await get_store(user_id)
    new_state = SessionState()
    new_state.session_id = store.current_id  # keep its place in history
    store.sessions[store.current_id] = new_state
    await persist(user_id, new_state)
    return new_state.to_payload()


@app.get("/sessions")
async def list_sessions(user_id: str = Depends(get_current_user_id)) -> list[dict]:
    store = await get_store(user_id)
    return store.list_sessions()


@app.post("/sessions/new")
async def new_session(user_id: str = Depends(get_current_user_id)) -> dict:
    """The actual feature requested: reset the live graph for a new chat, while
    keeping every previous session in history rather than discarding it.
    """
    store = await get_store(user_id)
    state = store.new_session()
    await persist(user_id, state)
    return state.to_payload()


@app.post("/sessions/switch")
async def switch_session(req: SwitchSessionRequest, user_id: str = Depends(get_current_user_id)) -> dict:
    store = await get_store(user_id)
    try:
        state = store.switch(req.session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"No session with id {req.session_id!r}")
    return state.to_payload()


async def _process_message(session: SessionState, message: str, user_id: str) -> tuple[str, str]:
    """The actual "what should happen for this message" logic, shared between a
    normal /chat turn and /chat/regenerate -- pulled out so regenerating a
    reply re-runs EXACTLY the same dispatch a fresh message would, rather than
    a second, drifting copy of it. Does not touch session.messages itself;
    callers own when a user/agent message gets appended.
    """
    # Bring-your-own-key: resolved once per request, right before any LLM call
    # this turn could possibly make. set_current_user_keys is a ContextVar set
    # (llm_config.py) -- scoped to this request's own asyncio Task, so a
    # concurrent request from a different user can never see or clobber it.
    set_current_user_keys(_resolve_provider_keys(await _get_user_keys(user_id)))

    # docs/Architecture.md §0.20: confirmation detection runs FIRST, every turn,
    # unconditionally -- before parse_intent ever sees the message. This is the
    # actual fix, not a special case for the word "yes": deterministic
    # conversational state decides what a confirmation means, never an LLM
    # guess, because a bare "yes" carries no content for a classifier to work
    # with and — confirmed live — will be fabricated into a full
    # new_investigation rather than admitted as unknown.
    confirmation = _classify_confirmation(message)
    if confirmation is not None:
        if session.pending_action is None:
            reply = "There's nothing pending for me to confirm right now — what would you like to explore?"
            intent_action = "no_action"
        elif confirmation:
            reply = await _execute_pending_action(session, session.pending_action)
            intent_action = session.pending_action.action
        else:
            reply = "Okay, skipping that."
            intent_action = "no_action"
        session.pending_action = None
        return reply, intent_action

    # Not a yes/no-shaped reply -- per §0.20's lifecycle policy, a new topic
    # clears any stale offer rather than leaving it to be accidentally
    # confirmed several turns later.
    session.pending_action = None
    context = SessionContext(
        current_entity=session.current_entity,
        current_abstraction=session.current_abstraction,
        known_entities=session.known_entities,
    )
    intent = await parse_intent(message, context)
    handler = _HANDLERS.get(intent.action)
    if handler is None:
        reply = f"I don't know how to handle intent: {intent.action}"
    else:
        try:
            reply = await handler(session, intent)
        except Exception as exc:  # noqa: BLE001 - surface to the demo UI instead of a 500
            reply = f"Something went wrong investigating that: {exc}"
    return reply, intent.action


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, user_id: str = Depends(get_current_user_id)) -> ChatResponse:
    store = await get_store(user_id)
    session = store.current()
    session.add_message("user", req.message)
    reply, intent_action = await _process_message(session, req.message, user_id)
    session.add_message("agent", reply, intent_action=intent_action, entity_name=session.current_entity)
    await persist(user_id, session)
    return ChatResponse(reply=reply, intent_action=intent_action, graph=session.to_payload())


@app.post("/chat/regenerate", response_model=ChatResponse)
async def regenerate(user_id: str = Depends(get_current_user_id)) -> ChatResponse:
    """Re-runs the LAST turn only -- by construction, not by trusting a message
    id/index the client sends. There is no parameter naming which message to
    regenerate; this always operates on session.messages[-1], so an older
    reply can never be regenerated even by a stale/replayed request. An error
    can be permanent otherwise (a bad or failed answer just sits there) --
    this exists so the single most recent reply can be retried without
    resending the question or losing the rest of the conversation.
    """
    store = await get_store(user_id)
    session = store.current()
    if len(session.messages) < 2 or session.messages[-1].role != "agent" or session.messages[-2].role != "user":
        raise HTTPException(status_code=400, detail="Nothing to regenerate — no prior agent reply to a user message.")
    last_user_text = session.messages[-2].text
    session.messages.pop()  # remove only the last agent reply, never anything earlier
    reply, intent_action = await _process_message(session, last_user_text, user_id)
    session.add_message("agent", reply, intent_action=intent_action, entity_name=session.current_entity)
    await persist(user_id, session)
    return ChatResponse(reply=reply, intent_action=intent_action, graph=session.to_payload())


@app.get("/resources")
async def resources(entity_name: str, user_id: str = Depends(get_current_user_id)) -> list[dict]:
    """Every source behind a given entity's investigated questions, aggregated
    and de-duplicated by URL. Read-only -- resolves the entity via the same
    find_or_create_entity every other read path uses (idempotent; a brand-new
    entity just comes back with an empty list, not an error).
    """
    entity = await find_or_create_entity(entity_name)
    questions = await get_questions_for_entity(entity.id)
    seen_urls: set[str] = set()
    results: list[dict] = []
    for question in questions:
        for claim in await get_claims_for_question(question.id):
            if claim.source_url in seen_urls:
                continue
            seen_urls.add(claim.source_url)
            results.append(
                {
                    "title": claim.source_title,
                    "url": claim.source_url,
                    "source_type": claim.source_type,
                }
            )
    return results


# Clean-URL routes for the two real pages. StaticFiles(html=True) below only
# auto-resolves "index.html" for a directory-style path ("/" -> index.html) —
# it does NOT append ".html" to arbitrary extension-less paths the way
# Vercel's cleanUrls does (verified directly: /chat 404'd against the mount
# alone). Registered as explicit GET routes, ahead of the mount, so /chat
# (a page) and the existing POST /chat (the API endpoint) coexist without
# conflict — FastAPI routes on method, not path alone.
@app.get("/chat")
async def chat_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "chat.html")


@app.get("/home")
async def home_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/app.html")
async def legacy_app_html_redirect() -> RedirectResponse:
    """The tool's page used to live at /app.html before the /chat rename —
    redirect old links/bookmarks instead of 404ing them."""
    return RedirectResponse(url="/chat")


# Serves the whole frontend/ directory (index.html landing page, chat.html the
# actual tool) — html=True makes "/" resolve to index.html the same way static
# hosts like Vercel do. Registered LAST and deliberately: a mount at "/" would
# otherwise match every path as a prefix and swallow the API routes above it
# if it were registered first, since Starlette checks routes in registration
# order.
app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
