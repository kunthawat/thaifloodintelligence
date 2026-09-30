"""Provider connector contracts and bounded HTTPS transport."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_METADATA_BYTES = 2 * 1024 * 1024
USER_AGENT = "ThailandFloodIntelligence/0.2 (+https://localhost; source attribution preserved)"


@dataclass(frozen=True)
class ConnectorBlocker:
    source_id: str
    code: str
    detail: str


class ConnectorNotConfigured(RuntimeError):
    def __init__(self, blocker: ConnectorBlocker):
        self.blocker = blocker
        super().__init__(f"{blocker.source_id}: {blocker.detail}")


class BlockedConnector:
    """Compatibility wrapper for integrations with an external blocker."""

    def __init__(self, source_id: str, provider: str, missing: str):
        self.source_id = source_id
        self.provider = provider
        self.blocker = ConnectorBlocker(source_id, "NOT_CONFIGURED", missing)

    async def fetch(self, *_: object, **__: object) -> list[dict[str, object]]:
        raise ConnectorNotConfigured(self.blocker)


@dataclass(frozen=True)
class TimeWindow:
    start: datetime | None = None
    end: datetime | None = None


@dataclass(frozen=True)
class DiscoveryResult:
    source_id: str
    status: str
    endpoint: str | None
    resources: tuple[dict[str, str], ...] = ()
    schema_version: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RawRecord:
    source_id: str
    record_id: str | None
    payload: dict[str, Any]
    observed_at: str | None = None


@dataclass(frozen=True)
class CanonicalObservation:
    entity_type: str
    entity_id: str
    variable: str
    value: float | None
    unit: str | None
    datum: str | None
    observed_at: str | None
    source_id: str
    source_record_id: str | None
    quality_state: str
    observation_type: str
    semantic_status: str
    raw_payload: dict[str, Any]
    physics_eligible: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticValidation:
    status: str
    verified_fields: tuple[str, ...] = ()
    blocked_fields: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    status: str
    checked_at: str
    http_status: int | None = None
    latency_ms: int | None = None
    last_observed_at: str | None = None
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class SourceConnector(Protocol):
    source_id: str

    async def healthcheck(self) -> dict[str, Any]: ...
    async def discover(self) -> DiscoveryResult: ...
    async def fetch(self, window: TimeWindow | None = None) -> list[RawRecord]: ...
    def normalize(self, raw: RawRecord) -> list[CanonicalObservation]: ...
    def validate_semantics(self) -> SemanticValidation: ...


class StaticDatasetConnector(Protocol):
    source_id: str

    async def discover_version(self) -> DiscoveryResult: ...
    async def download(self, discovery: DiscoveryResult) -> list[str]: ...
    def validate(self, paths: list[str]) -> dict[str, Any]: ...
    def import_dataset(self, paths: list[str]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HTTPResponse:
    url: str
    status: int
    content_type: str
    body: bytes
    latency_ms: int

    @property
    def text(self) -> str:
        return self.body.decode("utf-8-sig", errors="replace")


class _HTTPSRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Request | None:
        old = urlparse(req.full_url)
        new = urlparse(newurl)
        if old.scheme == "https" and new.scheme != "https":
            raise URLError("refused HTTPS downgrade redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, *, params: dict[str, str] | None = None, headers: dict[str, str] | None = None, timeout: float = 5, max_bytes: int = MAX_METADATA_BYTES) -> HTTPResponse:
    if params:
        joiner = "&" if "?" in url else "?"
        url = url + joiner + urlencode(params)
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("source endpoint must be an absolute HTTPS URL")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html,application/pdf,*/*", **(headers or {})})
    opener = build_opener(_HTTPSRedirectHandler())
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ValueError(f"response exceeded {max_bytes} byte metadata limit")
            return HTTPResponse(response.geturl(), response.status, response.headers.get("Content-Type", ""), body, round((time.monotonic() - started) * 1000))
    except HTTPError as exc:
        return HTTPResponse(exc.geturl(), exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", b"", round((time.monotonic() - started) * 1000))


async def fetch_https(url: str, **kwargs: Any) -> HTTPResponse:
    return await asyncio.to_thread(_get, url, **kwargs)


def _get_prefix(url: str, *, max_bytes: int = 1024 * 1024, timeout: float = 12) -> HTTPResponse:
    """Bounded prefix for a reverse-chronological HTML report with no pagination."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("source endpoint must be an absolute HTTPS URL")
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    started = time.monotonic()
    opener = build_opener(_HTTPSRedirectHandler())
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(max_bytes)
            return HTTPResponse(response.geturl(), response.status,
                                response.headers.get("Content-Type", ""), body,
                                round((time.monotonic() - started) * 1000))
    except HTTPError as exc:
        return HTTPResponse(exc.geturl(), exc.code, exc.headers.get("Content-Type", "") if exc.headers else "",
                            b"", round((time.monotonic() - started) * 1000))


async def fetch_https_prefix(url: str, **kwargs: Any) -> HTTPResponse:
    return await asyncio.to_thread(_get_prefix, url, **kwargs)


def decode_json(response: HTTPResponse) -> Any:
    return json.loads(response.body.decode("utf-8-sig"))


class AnchorParser(HTMLParser):
    """Collect anchor labels, image alt text, and hrefs without scraping scripts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or "" for key, value in attrs}
        if tag.lower() == "a":
            self._current = {"href": values.get("href", ""), "text": "", "title": values.get("title", ""), "alt": ""}
        elif tag.lower() == "img" and self._current is not None:
            self._current["alt"] = values.get("alt", "")

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._current["text"] += data.strip() + " "

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._current is not None:
            for key in ("text", "title", "alt"):
                self._current[key] = " ".join(self._current[key].split())
            self.anchors.append(self._current)
            self._current = None


def anchors(html: str) -> list[dict[str, str]]:
    parser = AnchorParser()
    parser.feed(html)
    return parser.anchors


def absolute_resource(base: str, href: str) -> str:
    result = urljoin(base, href)
    if urlparse(result).scheme != "https":
        raise ValueError("discovered resource did not resolve to HTTPS")
    return result


def parse_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    from math import isfinite
    return number if isfinite(number) else None
