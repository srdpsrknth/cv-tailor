"""HTTP access for job connectors, with the ADR 0008 §3 obligations built in.

ADR 0008 §3 requires that any network access *"identify itself honestly, respect
``robots.txt``, and be isolated behind the connector interface so it can be
disabled without breaking anything else."* This module is where the first two are
enforced structurally rather than remembered:

* **An honest User-Agent is the default, not an option.** :func:`build_user_agent`
  is the only place one is constructed, so no connector can forget or spoof it.
* **A request budget is enforced, not documented.** :class:`JobHttpClient` counts
  requests and refuses to exceed its budget, so no single connector can hammer a
  source even by accident.
* **Per-host pacing.** Even a well-behaved connector that pages through 30 results
  must not issue thirty back-to-back requests, so there is a minimum interval
  between requests to the same host.

**Robots.** The connectors built in Phase 4 talk to *published, documented APIs*
whose operators invite machine access (softgarden's DataFeed, Personio's XML feed,
Lever/Greenhouse/Ashby's posting APIs). They are not crawl targets, so
``robots.txt`` does not gate them. That is a deliberate reading, recorded here
because it is the kind of assumption that silently becomes wrong:
:class:`RobotsPolicy` exists so that a future connector which *does* read a website
has a checked path to follow rather than an excuse to skip it. The connectors that
failed that bar in research (StepStone, Indeed, LinkedIn, and SmartRecruiters,
whose API host disallows every crawler) are **not implemented at all** -- the
honest way to respect a refusal is to not make the request.

**Testing.** No test may make a network call. :class:`RecordingTransport` replays
payloads captured from the real endpoints, so the connectors are exercised against
authentic shapes offline.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from models.job import JobSourceError, user_agent

#: Default ceiling on network requests for one search run. Deliberately modest:
#: Phase 4 can reach its DACH sources within this, and a bug that loops cannot
#: turn into a flood.
DEFAULT_REQUEST_BUDGET = 60

#: Minimum seconds between requests to the same host.
DEFAULT_MIN_INTERVAL = 0.5

#: Request timeout. Generous, because some of these feeds are megabytes.
DEFAULT_TIMEOUT = 30.0


def build_user_agent(version: str = "0.4") -> str:
    """The honest User-Agent sent by every connector. Built in one place."""
    return user_agent(version)


@dataclass
class HttpResponse:
    """A minimal response, so connectors do not depend on urllib types."""

    status: int
    body: bytes
    headers: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self):
        """Parse JSON, raising a connector error rather than a decode error."""
        try:
            return json.loads(self.text)
        except json.JSONDecodeError as error:
            raise JobSourceError("http", f"response was not JSON: {error}") from error


class Transport:
    """How bytes are obtained. Swapped for a recorder in tests."""

    def get(self, url: str, headers: Optional[dict] = None) -> HttpResponse:
        raise NotImplementedError


class UrlLibTransport(Transport):
    """The real transport: ``urllib`` with an honest User-Agent and a timeout."""

    def __init__(self, timeout: float = DEFAULT_TIMEOUT, agent: Optional[str] = None):
        self.timeout = timeout
        self.agent = agent or build_user_agent()

    def get(self, url: str, headers: Optional[dict] = None) -> HttpResponse:
        request = urllib.request.Request(url, method="GET")
        request.add_header("User-Agent", self.agent)
        request.add_header("Accept", "application/json, application/xml, text/xml, */*")
        for key, value in (headers or {}).items():
            request.add_header(key, value)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return HttpResponse(
                    status=response.status,
                    body=response.read(),
                    headers=dict(response.headers),
                )
        except urllib.error.HTTPError as error:
            # An HTTP error is still a response; the connector decides what it means.
            return HttpResponse(status=error.code, body=error.read(),
                                headers=dict(error.headers or {}))
        except urllib.error.URLError as error:
            raise JobSourceError("http", f"could not reach {url}: {error.reason}",
                                 retryable=True) from error
        except Exception as error:  # noqa: BLE001 - converted, never leaked
            raise JobSourceError("http", f"request to {url} failed: {error}",
                                 retryable=True) from error


class RecordingTransport(Transport):
    """Replays captured payloads. Used by tests so they never touch the network.

    Keys are the request URL; a missing key is an error rather than a live fetch,
    so a test that reaches for an uncaptured URL fails loudly instead of silently
    going online.
    """

    def __init__(self, responses: dict):
        self.responses = dict(responses)
        self.calls: list = []

    def get(self, url: str, headers: Optional[dict] = None) -> HttpResponse:
        self.calls.append(url)
        if url not in self.responses:
            raise AssertionError(
                f"RecordingTransport has no captured response for {url!r}. Tests "
                "must not make network calls; add a fixture instead."
            )
        entry = self.responses[url]
        if isinstance(entry, HttpResponse):
            return entry
        if isinstance(entry, bytes):
            return HttpResponse(status=200, body=entry)
        if isinstance(entry, str):
            return HttpResponse(status=200, body=entry.encode("utf-8"))
        # A dict payload is serialised, so fixtures can be readable JSON.
        return HttpResponse(status=200, body=json.dumps(entry).encode("utf-8"))


def load_recorded_transport(path, base_urls: Optional[dict] = None) -> RecordingTransport:
    """Build a :class:`RecordingTransport` from a captured-payload JSON file.

    ``base_urls`` maps a fixture key to the URL it stands for, so the file can use
    readable names instead of long query strings.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    mapping = dict(base_urls or {})
    responses = {}
    for key, value in payload.items():
        if key.startswith("_"):
            continue
        responses[mapping.get(key, key)] = value
    return RecordingTransport(responses)


class RobotsPolicy:
    """Checks ``robots.txt`` before a *website* (not an API) is read.

    Unused by the Phase 4 connectors, which speak to documented APIs, and kept
    because the next connector that reads a career page must have a checked path
    to follow. Caching is per-host and in-memory, so one search does not fetch the
    same ``robots.txt`` repeatedly.
    """

    def __init__(self, transport: Transport):
        self.transport = transport
        self._cache: dict = {}

    def _parser(self, url: str) -> Optional[RobotFileParser]:
        parsed = urlparse(url)
        host = f"{parsed.scheme}://{parsed.netloc}"
        if host in self._cache:
            return self._cache[host]
        robots_url = f"{host}/robots.txt"
        parser = None
        try:
            response = self.transport.get(robots_url)
            if response.status == 200:
                parser = RobotFileParser()
                parser.parse(response.text.splitlines())
        except JobSourceError:
            # An unreachable robots.txt must not silently grant permission.
            parser = None
        self._cache[host] = parser
        return parser

    def allowed(self, url: str, agent: Optional[str] = None) -> bool:
        """True only when ``robots.txt`` was fetched and permits this URL."""
        parser = self._parser(url)
        if parser is None:
            return False
        return parser.can_fetch(agent or build_user_agent(), url)


@dataclass
class JobHttpClient:
    """A budgeted, paced HTTP client shared by the connectors.

    The budget and pacing exist so a connector bug degrades into a slow search
    rather than a flood of requests against a source that has been generous enough
    to publish an open API.
    """

    transport: Transport = field(default_factory=UrlLibTransport)
    request_budget: int = DEFAULT_REQUEST_BUDGET
    min_interval: float = DEFAULT_MIN_INTERVAL
    timeout: float = DEFAULT_TIMEOUT
    #: Injectable clock, so pacing is testable without real sleeping.
    clock: object = time.monotonic
    sleeper: object = time.sleep
    requests_made: int = 0
    _last_by_host: dict = field(default_factory=dict)

    def get(self, url: str, source: str = "http",
            headers: Optional[dict] = None) -> HttpResponse:
        """Fetch ``url``, honouring the budget and per-host pacing."""
        if self.requests_made >= self.request_budget:
            raise JobSourceError(
                source,
                f"request budget exhausted ({self.request_budget} requests). "
                "Increase --max-requests to search further.",
            )
        host = urlparse(url).netloc
        last = self._last_by_host.get(host)
        if last is not None and self.min_interval > 0:
            elapsed = self.clock() - last
            remaining = self.min_interval - elapsed
            if remaining > 0:
                self.sleeper(remaining)
        try:
            response = self.transport.get(url, headers=headers)
        finally:
            self.requests_made += 1
            self._last_by_host[host] = self.clock()
        return response

    def get_json(self, url: str, source: str, headers: Optional[dict] = None):
        """Fetch and parse JSON, raising a source error on a non-200."""
        response = self.get(url, source=source, headers=headers)
        if response.status != 200:
            raise JobSourceError(
                source,
                f"{url} returned HTTP {response.status}",
                retryable=response.status >= 500 or response.status == 429,
            )
        return response.json()

    def get_text(self, url: str, source: str, headers: Optional[dict] = None) -> str:
        """Fetch text (e.g. an XML feed), raising a source error on a non-200."""
        response = self.get(url, source=source, headers=headers)
        if response.status != 200:
            raise JobSourceError(
                source,
                f"{url} returned HTTP {response.status}",
                retryable=response.status >= 500 or response.status == 429,
            )
        return response.text
