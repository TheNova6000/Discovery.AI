"""Dewey's read-through engine: Archive first, research only on a miss
(docs/research/Reasoning-Research-Orchestration.md §2b).

    need -> Archive.query -> covered?            yes -> EvidenceBatch(source="archive")
                             no -> ledger: known gap, retry not due? -> "known_gap"
                             no -> providers -> ingest -> Archive.query -> "research"

Until safe page fetching lands (build step 3) a provider result is ingested
as title + snippet, the same text the evidence engine sees today.
"""

from __future__ import annotations

import math
import os
import re
from datetime import timedelta

from .resource import RetrievedResource

from .archive import ArchiveStore, Document, PassageHit, content_terms, query_words
from .contracts import EvidenceBatch, InformationNeed, ProviderReport
from .fetch import FetchError, SafeFetcher
from .providers import ProviderRegistry

MIN_TERM_COVERAGE = 0.5
RELEVANCE_GATE = 0.34
"""A passage covering under a third of the need's content terms is kept in the
Archive but not handed to the reasoning engine -- CRAG-style "grade before use"
(iteration 01, E8: arXiv physics papers reached LLM synthesis for "binary
search tree"). Cheap and deterministic: no LLM call is spent on it."""
RESULTS_PER_PROVIDER = 3
MAX_FETCHES_PER_NEED = 2
"""Full pages read per researched need -- the best-matching non-metadata results
only (iteration 02: the evidence gaps live run 6 listed were all in the body of a
page whose summary Dewey already had)."""
CANDIDATE_POOL_FACTOR = 4
"""Retrieve a wider candidate pool from the Archive, then relevance-gate and
rerank down to `max_passages` (standard retrieve-then-rerank). With the pool
equal to the output size, junk passages ranked by raw BM25 crowded out the
relevant Wikipedia sections (iteration 02, run 7: root question got none)."""
FETCH_GATE = 0.15
"""Lower bar for choosing which results to READ in full than for passing a
passage to the LLM: a 2-sentence summary shares few words with a detailed
question even when its page answers it (loop iteration 05, E15: the Wikipedia
"Photosynthesis" article was never read). Reading is cheap; the full text then
goes through RELEVANCE_GATE like everything else."""
DEEP_KINDS = frozenset({"full_text", "excerpt"})
"""Passage kinds that can explain a mechanism. Summaries and abstracts alone
don't count as covering a need (except evidence needs, where an abstract is the
right unit) -- otherwise a 2-sentence summary blocks the full read forever."""

# How long the ledger trusts an outcome before the same need may be searched again.
RETRY_AFTER = {
    "found": timedelta(days=7),
    # Wrapped retrievers report a rate limit as an empty result, so "nothing"
    # is often "blocked right now" -- retry within hours, not a day.
    "weak_results": timedelta(hours=6),
    "nothing_found": timedelta(hours=6),
    "providers_failed": timedelta(hours=1),
}


def term_coverage(need_text: str, passage_text: str) -> float:
    """Fraction of the need's content terms that appear in the passage."""
    need_terms = content_terms(need_text)
    if not need_terms:
        return 0.0
    passage_terms = set(content_terms(passage_text))
    return sum(1 for t in need_terms if t in passage_terms) / len(need_terms)


def _covered(need: InformationNeed, hits: list[PassageHit]) -> bool:
    # Metadata (a repo/book/video description) can mention every term of a need
    # without explaining anything -- iteration 01 run 6: GitHub + Open Library
    # records marked "operations of a BST and their costs" as covered for a week.
    strong = [
        h for h in hits
        if h.content_kind != "metadata" and term_coverage(need.text, h.title + " " + h.text) >= MIN_TERM_COVERAGE
    ]
    deep_enough = need.need_kind == "evidence" or any(h.content_kind in DEEP_KINDS for h in strong)
    return len(strong) >= need.min_passages and deep_enough


def _document(resource: RetrievedResource, provider: str) -> Document:
    return Document(
        url=resource.url,
        title=resource.title,
        provider=provider,
        source_type=resource.source_type,
        source_role=resource.source_role,
        acquisition_mode=resource.acquisition_mode,
        content_kind=resource.content_kind,
        published=resource.published,
        retrieved_at=resource.retrieved_at,
    )


def _deliverable(need: InformationNeed, hits: list[PassageHit], idf: dict[str, float] | None = None) -> list[PassageHit]:
    """Relevance-gated, metadata after content (a reliability prior on source
    kind; arXiv 2607.22584), then ranked by how many of the need's DISTINCTIVE
    terms a passage contains (archive-level IDF), then BM25 -- cut to
    `need.max_passages`."""
    relevant = [h for h in hits if term_coverage(need.text, h.title + " " + h.text) >= RELEVANCE_GATE]
    weights = idf or {}
    key_terms = sorted(weights, key=lambda t: -weights[t])[:KEY_TERMS]
    need_terms = set(content_terms(need.text))
    definitional = bool(_DEFINITIONAL.match(need.text))

    def distinctive(h: PassageHit) -> float:
        terms = set(content_terms(h.title + " " + h.text))
        score = sum(w for t, w in weights.items() if t in terms)
        heading = _SECTION.match(h.text)
        if heading:
            # A passage whose own section heading names a DISTINCTIVE need term is
            # ABOUT it ("Section: Insertion"); headings sharing only the common
            # terms ("Balanced binary search trees") get no bonus.
            heading_terms = set(content_terms(heading.group(1)))
            score += HEADING_BONUS * sum(weights[t] for t in key_terms if t in heading_terms)
        # The document's own title naming a distinctive need term ("Calvin cycle")
        # separates on-topic pages from look-alikes ("Input-Output Theory ...").
        title_terms = set(content_terms(h.title))
        score += TITLE_BONUS * sum(weights[t] for t in key_terms if t in title_terms)
        if definitional and h.position == 0 and title_terms and title_terms <= need_terms:
            # "What is X?" is answered by the lead of X's own page (the lead
            # section summarises the article) -- it carries no section header.
            score += LEAD_BONUS * sum(weights.get(t, 0.0) for t in title_terms)
        return score

    unique: dict[str, PassageHit] = {}
    for h in relevant:
        unique.setdefault(h.passage_id, h)
    return sorted(unique.values(), key=lambda h: (h.content_kind == "metadata", -distinctive(h), -h.score))[: need.max_passages]


HEADING_BONUS = 3.0
KEY_TERMS = 3
TITLE_BONUS = 1.0
LEAD_BONUS = 3.0
_DEFINITIONAL = re.compile(r"^\s*(what (is|are)( an?| the)?|define|definition of|meaning of)\b", re.I)
# Chosen by measurement (scripts/evaluate_dewey_retrieval.py --grid).
_SECTION = re.compile(r"^Section: ([^.]{1,60})\.")

PER_TERM_POOL = 4
"""Passages pulled per need term on top of the BM25 pool, so a passage carrying
a rare, decisive term ("insertion") enters the pool even when common terms
("binary search tree") dominate the OR-query ranking (loop iteration 05, E19:
the Insertion section ranked 19th of 170 against a pool of 16)."""


async def _candidate_pool(archive: ArchiveStore, need: InformationNeed) -> tuple[list[PassageHit], dict[str, float]]:
    pool = await archive.query(need.text, limit=need.max_passages * CANDIDATE_POOL_FACTOR)
    # Stemmed term (for matching passages) -> an original word (for FTS, which stems itself).
    original: dict[str, str] = {}
    for word in query_words(need.text):
        original.setdefault(content_terms(word)[0] if content_terms(word) else word, word)
    terms = content_terms(need.text)
    df, total = await archive.term_document_frequencies([original.get(t, t) for t in terms])
    idf = {t: math.log(1 + (total or 1) / (1 + df.get(original.get(t, t), 0))) for t in terms}
    for term in sorted(terms, key=lambda t: -idf[t])[:4]:
        pool += await archive.query(original.get(term, term), limit=PER_TERM_POOL)
    return pool, idf


class DeweyEngine:
    def __init__(
        self,
        archive: ArchiveStore,
        registry: ProviderRegistry | None = None,
        fetcher: SafeFetcher | None = None,
    ) -> None:
        self.archive = archive
        self.registry = registry or ProviderRegistry()
        self.fetcher = fetcher or SafeFetcher()

    async def _read_full_pages(self, need: InformationNeed, resources) -> tuple[int, list[ProviderReport]]:
        """Fetch + extract the best few non-metadata results and ingest them as
        full text (a richer version of the same URL). DEWEY_FETCH=off skips this
        (offline runs, tests)."""
        if os.environ.get("DEWEY_FETCH", "on").lower() == "off":
            return 0, []
        candidates = sorted(
            (
                (term_coverage(need.text, r.title + " " + r.snippet), provider, r)
                for provider, r in resources
                # Abstracts are already the readable unit (the full paper is a PDF
                # behind the abstract page): reading them in full spent both fetches
                # on arXiv while the Wikipedia article went unread (iteration 05, Mitosis).
                if r.content_kind not in ("metadata", "full_text", "abstract") and r.url.startswith(("http://", "https://"))
            ),
            key=lambda t: -t[0],
        )
        seen: set[str] = set()
        added, reports = 0, []
        for coverage, provider, resource in candidates:
            if len(seen) >= MAX_FETCHES_PER_NEED or coverage < FETCH_GATE:
                break
            if resource.url in seen:
                continue
            seen.add(resource.url)
            try:
                page = await self.fetcher.fetch(resource.url)
            except FetchError as exc:
                reports.append(ProviderReport(provider=f"fetch:{provider}", status="failed", detail=f"{exc.kind} {resource.url}"[:200]))
                continue
            doc = _document(resource, provider)
            doc.content_kind = "full_text"
            doc.title = page.title or doc.title
            result = await self.archive.ingest(doc, page.text, entity_ids=[need.entity_id] if need.entity_id else None)
            added += result.passages_added
            reports.append(ProviderReport(provider=f"fetch:{provider}", status="ok", results=result.passages_added, detail=page.method))
        return added, reports

    async def find(self, need: InformationNeed) -> EvidenceBatch:
        hits, idf = await _candidate_pool(self.archive, need)
        if _covered(need, hits):
            return EvidenceBatch(need=need, passages=_deliverable(need, hits, idf), source="archive")

        entry = await self.archive.ledger_entry(need.text)
        if entry is not None and not entry.retry_due:
            return EvidenceBatch(need=need, passages=_deliverable(need, hits, idf), source="known_gap")

        resources, reports = await self.registry.search(need.need_kind, need.text, RESULTS_PER_PROVIDER)
        ingested = 0
        for provider, resource in resources:
            if not resource.snippet.strip():
                continue
            result = await self.archive.ingest(
                _document(resource, provider),
                f"{resource.title}\n\n{resource.snippet}",
                entity_ids=[need.entity_id] if need.entity_id else None,
            )
            ingested += result.passages_added
        fetched, fetch_reports = await self._read_full_pages(need, resources)
        ingested += fetched

        hits, idf = await _candidate_pool(self.archive, need)
        searched = [r for r in reports if r.status in ("ok", "no_results")]
        if not searched:
            outcome = "providers_failed"
        elif _covered(need, hits):
            outcome = "found"
        elif any(r.status == "ok" for r in reports):
            # Providers returned something, but none of it covers the need
            # (live BST run 4: arXiv physics papers, book titles, project lists).
            # Recording that as "found" would let junk answer this need for a week.
            outcome = "weak_results"
        else:
            outcome = "nothing_found"
        await self.archive.record_research(
            need.text,
            providers=[r.provider for r in reports if r.status != "skipped_no_key"],
            outcome=outcome,
            passages_added=ingested,
            retry_after=RETRY_AFTER[outcome],
        )

        # Whatever the Archive returns after a total provider outage is only what
        # it already held -- calling that "research" would hide the outage.
        source = "unavailable" if outcome == "providers_failed" else "research"
        return EvidenceBatch(
            need=need, passages=_deliverable(need, hits, idf), source=source,
            reports=reports + fetch_reports, passages_ingested=ingested,
        )
