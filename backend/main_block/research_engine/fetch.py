"""Dewey's safe page fetcher and text extractor (build step 3; loop iteration 02).

Why: live runs 5-6 showed the remaining evidence gaps ("exact steps for
insertion", "cost per operation") sitting in the *body* of pages Dewey had
already found, while only their 2-sentence summaries reached the reasoning
engine. Reading full pages is what deep-research systems do (GPT-Researcher's
scrape-and-filter step; Open Deep Research's sub-agents read sources).

Rules this module enforces (master prompt §4.2, §18):
- http/https only; every hop's host is resolved and refused if it is a private,
  loopback, link-local, multicast, reserved or unspecified address (SSRF),
  including after redirects (followed manually, max 3);
- robots.txt per RFC 9309: 2xx parsed and obeyed, 4xx = no restrictions,
  5xx/unreachable = assume disallowed;
- size cap, timeout, and a content-type allowlist (HTML, plain text, PDF);
- at least MIN_HOST_INTERVAL seconds between requests to one host;
- fetched text is data: nothing here interprets it.

Wikipedia articles are read through the official MediaWiki API
(`prop=extracts&explaintext`) rather than scraped, with the contact-bearing
User-Agent (see retrievers/base.py: how Wikipedia 429s were fixed).
"""

from __future__ import annotations

import asyncio
import io
import ipaddress
import re
import socket
import time
from typing import Callable, Literal, Optional
from urllib.parse import unquote, urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from pydantic import BaseModel

from backend.main_block.research_engine.sources.base import CONTACT_USER_AGENT

MAX_BYTES = 2_000_000
TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
MIN_HOST_INTERVAL = 1.0
MAX_PDF_PAGES = 30
_ALLOWED_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/pdf")
_WIKI_HOST = re.compile(r"^([a-z]{2,3})\.wikipedia\.org$")

FetchFailure = Literal["bad_scheme", "ssrf_blocked", "robots_denied", "http_error", "too_large", "bad_type", "timeout", "network", "empty"]


class FetchedPage(BaseModel):
    url: str
    final_url: str
    title: Optional[str] = None
    text: str
    content_type: str
    method: str  # "wikipedia_api" | "trafilatura" | "beautifulsoup" | "pdf" | "plain"


class FetchError(Exception):
    def __init__(self, kind: FetchFailure, detail: str = "") -> None:
        super().__init__(f"{kind}: {detail}" if detail else kind)
        self.kind = kind
        self.detail = detail


def _default_resolver(host: str) -> list[str]:
    return list({info[4][0] for info in socket.getaddrinfo(host, None)})


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified)


class SafeFetcher:
    """`transport` and `resolver` are injectable so tests run offline."""

    def __init__(
        self,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        resolver: Callable[[str], list[str]] = _default_resolver,
        min_host_interval: float = MIN_HOST_INTERVAL,
    ) -> None:
        self._transport = transport
        self._resolver = resolver
        self._min_interval = min_host_interval
        self._robots: dict[str, Optional[RobotFileParser]] = {}  # None = disallow all
        self._last_hit: dict[str, float] = {}
        self._host_locks: dict[str, asyncio.Lock] = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self._transport,
            headers={"User-Agent": CONTACT_USER_AGENT},
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
        )

    async def _check_host(self, url: str) -> str:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FetchError("bad_scheme", url)
        host = parts.hostname
        try:
            literal = ipaddress.ip_address(host)
            addresses = [str(literal)]
        except ValueError:
            try:
                addresses = await asyncio.to_thread(self._resolver, host)
            except OSError as exc:
                raise FetchError("network", f"cannot resolve {host}: {exc}") from exc
        if not addresses or not all(is_public_address(a) for a in addresses):
            raise FetchError("ssrf_blocked", f"{host} -> {addresses}")
        return host

    async def _polite(self, host: str) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last_hit.get(host, 0.0) + self._min_interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_hit[host] = time.monotonic()

    async def _get(self, client: httpx.AsyncClient, url: str) -> httpx.Response:
        """GET with manual redirects, re-checking every hop's host."""
        for _ in range(MAX_REDIRECTS + 1):
            host = await self._check_host(url)
            await self._polite(host)
            try:
                response = await client.get(url)
            except httpx.TimeoutException as exc:
                raise FetchError("timeout", url) from exc
            except httpx.HTTPError as exc:
                raise FetchError("network", str(exc)[:200]) from exc
            if response.is_redirect and "location" in response.headers:
                url = urljoin(url, response.headers["location"])
                continue
            return response
        raise FetchError("http_error", f"more than {MAX_REDIRECTS} redirects")

    async def _allowed_by_robots(self, client: httpx.AsyncClient, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin not in self._robots:
            parser: Optional[RobotFileParser] = RobotFileParser()
            try:
                response = await self._get(client, origin + "/robots.txt")
                if 200 <= response.status_code < 300:
                    parser.parse(response.text.splitlines())
                elif 400 <= response.status_code < 500:
                    parser.parse([])  # RFC 9309 §2.3.1.3: unavailable -> no restrictions
                else:
                    parser = None  # RFC 9309 §2.3.1.4: unreachable -> assume complete disallow
            except FetchError as exc:
                if exc.kind == "ssrf_blocked":
                    raise
                parser = None
            self._robots[origin] = parser
        parser = self._robots[origin]
        return parser is not None and parser.can_fetch(CONTACT_USER_AGENT, url)

    async def fetch(self, url: str) -> FetchedPage:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            # Checked up front: inside the robots lookup this error was swallowed
            # and the refusal mislabelled "robots_denied".
            raise FetchError("bad_scheme", url)
        wiki = _WIKI_HOST.match(parts.hostname)
        async with self._client() as client:
            if wiki and urlsplit(url).path.startswith("/wiki/"):
                return await self._fetch_wikipedia(client, url, wiki.group(1))
            if not await self._allowed_by_robots(client, url):
                raise FetchError("robots_denied", url)
            response = await self._get(client, url)
            if response.status_code >= 400:
                raise FetchError("http_error", f"{response.status_code} {url}")
            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if content_type not in _ALLOWED_TYPES:
                raise FetchError("bad_type", content_type or "missing")
            body = response.content
            if len(body) > MAX_BYTES:
                raise FetchError("too_large", f"{len(body)} bytes")
            title, text, method = _extract(body, content_type, url)
            if not text.strip():
                raise FetchError("empty", url)
            return FetchedPage(url=url, final_url=str(response.url), title=title, text=text, content_type=content_type, method=method)

    async def _fetch_wikipedia(self, client: httpx.AsyncClient, url: str, lang: str) -> FetchedPage:
        title = unquote(urlsplit(url).path[len("/wiki/"):]).replace("_", " ")
        api = (
            f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1"
            f"&redirects=1&format=json&formatversion=2&titles={httpx.QueryParams({'t': title})['t']}"
        )
        response = await self._get(client, api)
        if response.status_code >= 400:
            raise FetchError("http_error", f"{response.status_code} wikipedia api")
        pages = response.json().get("query", {}).get("pages", [])
        text = (pages[0].get("extract") or "") if pages else ""
        if not text.strip():
            raise FetchError("empty", url)
        return FetchedPage(url=url, final_url=url, title=pages[0].get("title"), text=_wiki_sections(text),
                           content_type="text/plain", method="wikipedia_api")


_DISPLAYSTYLE = re.compile(r"\{\\displaystyle\s*(.+?)\}\s*$")


def _clean_wiki_math(text: str) -> str:
    """Plain-text extracts spill each formula as one-symbol-per-line MathML text
    (indented) followed by its LaTeX `{\displaystyle ...}` line. Keep only the
    LaTeX, inline with the sentence around it."""
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        latex = _DISPLAYSTYLE.search(stripped)
        if latex:
            kept.append(f"${latex.group(1).strip()}$")
        elif line.startswith("  ") and len(stripped) <= 3:
            continue  # a spilled MathML symbol
        else:
            kept.append(line)
    merged: list[str] = []
    for line in kept:
        is_formula = line.startswith("$") and line.endswith("$")
        if merged and (is_formula or (merged[-1].startswith("$") and merged[-1].endswith("$"))) and line.strip():
            merged[-1] = f"{merged[-1].rstrip()} {line.strip()}"
        else:
            merged.append(line)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(merged))


def _wiki_sections(text: str) -> str:
    """'== Insertion ==' headings -> their own paragraphs, so chunking keeps a
    section's heading with its text; reference-only sections dropped."""
    text = _clean_wiki_math(text)
    out = re.sub(r"\n*(=+)\s*(.+?)\s*\1\n*", lambda m: f"\n\n{m.group(2)}\n", text)
    return re.split(r"\n\n(?:See also|References|Notes|Further reading|External links)\n", out)[0].strip()


def _extract(body: bytes, content_type: str, url: str) -> tuple[Optional[str], str, str]:
    if content_type == "application/pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(body))
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages[:MAX_PDF_PAGES])
        return None, text, "pdf"
    html = body.decode("utf-8", errors="replace")
    if content_type == "text/plain":
        return None, html, "plain"
    import trafilatura

    text = trafilatura.extract(html, url=url, include_comments=False, include_tables=True, favor_precision=True) or ""
    meta = trafilatura.extract_metadata(html)
    title = meta.title if meta else None
    if text.strip():
        return title, text, "trafilatura"
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.body or soup
    return title or (soup.title.string if soup.title else None), root.get_text("\n\n", strip=True), "beautifulsoup"
