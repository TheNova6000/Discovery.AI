# Main Block door (option B) and the Tuni'n chat model — as built (2026-10-28)

> Layout after the restructure: the door is `backend/main_block/` (public API `backend/main_block/interface.py`),
> engines in `main_block/reasoning_engine/` and `main_block/research_engine/`. See `docs/Architecture.md` → "Current code layout".

## The door: `backend/main_block` (import `backend.main_block.interface`)
Clients (chat model, Tuni'n portal) reach Discovery.AI + Dewey **only** through `backend.main_block.interface`.
`scripts/verify_mainblock_boundary.py` fails the build on any other import (the lesson-authoring calls the course side needs are exported through the interface too, so no legacy exceptions remain).

| Operation | Python | HTTP | Notes |
|---|---|---|---|
| Start research | `start_research(ResearchJobRequest, owner_id)` | `POST /mainblock/research` → 202 | idempotent per owner + normalised request; background, 1 concurrent job (`MAINBLOCK_MAX_CONCURRENT_JOBS`) |
| Job status / result | `get_job(job_id, owner_id)` | `GET /mainblock/research/{id}` | stages queued → investigating → compiling → completed / failed; other owners' jobs = 404; restart marks running jobs INTERRUPTED |
| Grounded question | `ask(AskRequest)` | `POST /mainblock/ask` | archive first, research on a miss, ≤2 gap searches; **never returns a memory draft as the answer** |

Every answer crossing the door is a `GroundedAnswer`: `grounded`, `support_ratio`, verified
`citations` (source, URL, content kind, retrieval time), `unsupported_statements`, `evidence_gaps`, `note`.
Jobs persist in `mainblock.sqlite3` (`MAINBLOCK_DB_PATH`).

`backend/tunin/research.py` (ResearchGateway) is now a thin client of the door (in-process, or
HTTP when `MAINBLOCK_URL` is set); its direct-retrieval path was deleted.

## The chat model: `backend/chat`
Separate from the reasoning engine: own model chain (`backend/chat/config.py`,
`TUNIN_CHAT_MODELS`), own prompts, reaches the engines only through `MainBlockPort` (default: `backend.main_block.interface`).

Phases: **discovery** (build the brief; learner questions → `mainblock.ask`) → **confirming**
(show brief, wait for explicit yes) → **researching** (real job stage) → **ready** (grounded
findings + gaps; course building is the owner-specified next part).
Routes: `POST /tunin/chat/sessions`, `GET /tunin/chat/sessions/{id}`,
`POST /tunin/chat/sessions/{id}/messages`. Sessions persist in `tunin_chat.sqlite3`.

Tests: `verify_mainblock` 8/8, `verify_chat` 15/15, `verify_mainblock_boundary` (holds).
Live: `scripts/evaluate_chat_live.py` (end-to-end conversation incl. a real research job).
