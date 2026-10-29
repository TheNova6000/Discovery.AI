"""Tuni'n — the adaptive, research-driven learning portal (root Memory.md).

Tuni'n is a *client* of Discovery.AI (`backend/main_block/reasoning_engine/graph`, `backend/main_block/reasoning_engine/agents`,
`backend/main_block/reasoning_engine/llm_steps`, `backend/main_block/reasoning_engine/evidence`, `backend/main_block/reasoning_engine/domain`,
`backend/main_block/reasoning_engine/research`, `backend/main_block/reasoning_engine/research_api`): it consumes Discovery.AI's
stable `ResearchResponse` and never builds a second research engine. Nothing
in Discovery.AI imports from this package.

Renamed 2026-10-28: this package absorbed what was `backend/main_block/research_engine`
(`coverage`, `lessons`, and `curriculum` -> `course`, to avoid colliding with
`tunin/curriculum.py`'s proposal compiler). The name **Dewey** now belongs to
the research engine — web search, fetching, extraction and indexing of
sources — after the Dewey Decimal System's job of classifying knowledge so it
can be found.
"""
