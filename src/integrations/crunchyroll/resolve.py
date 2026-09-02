"""CR series-code <-> MAL-id resolution.

**Seed map (E9a):** ``data/cr_mal_map.json`` was built from E10's ``resolved.json``
(the maintainer's own library, Jikan+TMDB resolved): 307 anime at confidence
high/override/medium; **low-confidence excluded** (the skip-don't-guess rule). C1 uses
:func:`mal_to_cr` to find a library item's CR code.

**CR -> MAL (E9b):** C2/C3 receive watchlist/history in CR's id space and must reach
the fork's MAL-keyed rows. :func:`cr_code_to_mal` tries the seed first, then a
**Jikan-search fallback** (port of E10's title scorer) gated to **exact-normalized
matches only** — a wrong MAL id would write status/progress onto the wrong show, so the
fallback follows the same skip-don't-guess rule as everywhere else (a non-exact match
returns ``None`` and the caller skips + reports). Resolutions (hits *and* genuine
misses) are cached in the Django cache so the daily beat doesn't re-hit Jikan for known
titles; a **Jikan outage is never cached** (see :class:`JikanSearchError`) so it can't
poison the cache as month-long unresolvable misses.

:func:`resolve_title_to_mal` is the shared title->MAL primitive; D3's hybrid
multi-season path reuses it to resolve each CR *season* title to its own MAL id.
"""

import json
import logging
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path

import requests
from django.core.cache import cache

logger = logging.getLogger(__name__)

SEED_PATH = Path(__file__).parent / "data" / "cr_mal_map.json"


class JikanSearchError(RuntimeError):
    """Jikan was unreachable or returned a non-200/parseable response.

    Raised so callers can tell a *transient outage* apart from a *real miss*: a
    successful search with no candidate returns ``[]`` (a cacheable miss), while a
    failed fetch raises this (and must **never** be cached as unresolvable — that's how
    the 2026-08-24 outage became month-long misses). ``args[0]`` is the query.
    """

# Public web base for series deep-links (E6). CR redirects the code-only
# /series/{code} URL to the canonical slug, so no slug lookup is needed.
WEB_BASE = "https://www.crunchyroll.com"

# Jikan (unofficial MAL API, no key) — same source E10's resolver used. Kept behind
# _jikan_search so tests stub exactly one function and the rate-limit sleep never runs
# under test.
JIKAN_URL = "https://api.jikan.moe/v4/anime"
JIKAN_TIMEOUT = 25
SEARCH_LIMIT = 6

# 429 (rate-limited) and 5xx (Jikan gateway timeouts) are transient: retry with capped
# exponential backoff instead of failing the title on the first hit. A dead Jikan still
# fails fast (a bounded number of attempts, never a month-long cached miss).
JIKAN_MAX_ATTEMPTS = 4
JIKAN_BASE_BACKOFF = 1.5
JIKAN_MAX_WAIT = 8
JIKAN_RATE_LIMITED = 429
JIKAN_INTERNAL_ERROR = 500

# Resolutions are stable; cache hits and misses for a month so the daily beat is
# Jikan-polite. A miss is cached as the empty string (distinct from a cache absence).
RESOLVE_CACHE_TTL = 60 * 60 * 24 * 30
_MISS = ""

_STOPWORDS = re.compile(r"\b(the|a|an)\b")


@lru_cache(maxsize=1)
def load_cr_mal_map():
    """Return the static ``{cr_code: mal_id}`` seed (both values are ``str``).

    Cached for the process; the file is static. Treat the result as read-only.
    """
    with SEED_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def mal_to_cr():
    """Return the inverse ``{mal_id: cr_code}`` map (the seed is 1:1, verified).

    C1's lookup direction: a library anime is keyed by MAL id and needs its CR code to
    find the catalog entry. Treat the result as read-only.
    """
    return {mal_id: code for code, mal_id in load_cr_mal_map().items()}


def series_url(mal_id):
    """Return the Crunchyroll series web URL for a MAL id, or ``None`` (E6).

    A library anime is keyed by MAL id; the E9a CR<->MAL seed maps it to its CR
    series code, whose public web URL is ``/series/{code}`` (CR redirects the
    code-only URL to the canonical slug). Returns ``None`` when the id isn't in the
    seed -- we don't guess a code (the resolver's skip-don't-guess rule). Used by
    E6's streaming-link tag.
    """
    code = mal_to_cr().get(str(mal_id))
    return f"{WEB_BASE}/series/{code}" if code else None


# --------------------------------------------------------------------------- #
# CR -> MAL resolution (E9b): seed first, then an exact-only Jikan fallback
# --------------------------------------------------------------------------- #


def normalize(text):
    """Fold a title to a comparable form (ascii, lowercase, no punctuation).

    Ported from E10's resolver so the seed and the live fallback score titles the same
    way: NFKD strip accents, lowercase, ``&``->``and``, drop punctuation + leading
    articles, collapse whitespace.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = _STOPWORDS.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _retryable(code):
    """Return True iff a Jikan failure is transient and worth retrying.

    ``None`` is a network/timeout error before any HTTP response; ``429``
    (``JIKAN_RATE_LIMITED``) is a rate limit (the main burst symptom on the daily
    beat); ``>= JIKAN_INTERNAL_ERROR`` is a Jikan gateway blip. A 4xx client error
    (e.g. a malformed ``q``) is NOT transient — retrying it would just burn the same
    rate-limit budget.
    """
    return (
        code is None
        or code == JIKAN_RATE_LIMITED
        or (code is not None and code >= JIKAN_INTERNAL_ERROR)
    )


def _retry_delay(resp, attempt):
    """Seconds to wait before the next attempt (capped so a dead Jikan can't stall).

    A 429 honours Jikan's ``Retry-After`` (capped); otherwise capped exponential
    backoff as ``attempt`` grows. ``resp`` is the last response, or ``None`` on a
    network error with no response.
    """
    if resp is not None:
        raw = resp.headers.get("Retry-After")
        if raw:
            try:
                return min(float(raw), JIKAN_MAX_WAIT)
            except (TypeError, ValueError):
                pass
    return min(JIKAN_BASE_BACKOFF * (2 ** (attempt - 1)), JIKAN_MAX_WAIT)


def _jikan_search(query):
    """Return Jikan anime candidates for ``query`` as ``[{mal_id, titles}]``.

    Returns ``[]`` only for a *successful* search that found no candidates. A network /
    response / parse failure raises :class:`JikanSearchError` — so the caller can
    distinguish a genuine miss (cacheable) from an outage (never cache). Tests stub
    this one function; the rate-limit sleep/retries never run under test.

    Transient failures (429 rate-limit, 5xx, timeouts, connection errors) are retried
    up to ``JIKAN_MAX_ATTEMPTS`` with capped backoff (:func:`_retry_delay`, honouring
    ``Retry-After`` on 429), so a momentary blip resolves instead of being counted as
    an error. Once every attempt fails we raise, leaving the key **uncached** so the
    next beat retries rather than carrying a stale month-long miss (the 2026-08-24
    outage bug).
    """
    data = None
    for attempt in range(1, JIKAN_MAX_ATTEMPTS + 1):
        time.sleep(0.5)  # Jikan is ~3 req/s; be polite (never runs under test)
        resp = None
        try:
            resp = requests.get(
                JIKAN_URL,
                params={"q": query, "limit": SEARCH_LIMIT},
                timeout=JIKAN_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except (requests.exceptions.RequestException, ValueError) as exc:
            code = None if resp is None else resp.status_code
            if not _retryable(code) or attempt == JIKAN_MAX_ATTEMPTS:
                logger.warning(
                    "Jikan search failed for %r after %s attempts",
                    query,
                    JIKAN_MAX_ATTEMPTS,
                )
                raise JikanSearchError(query) from exc
            time.sleep(_retry_delay(resp, attempt))

    candidates = []
    for node in (data or {}).get("data", []):
        titles = [
            node.get("title"),
            node.get("title_english"),
            node.get("title_japanese"),
        ]
        titles += [t.get("title") for t in node.get("titles", []) if t.get("title")]
        candidates.append(
            {
                "mal_id": str(node["mal_id"]),
                "titles": [t for t in titles if t],
            },
        )
    return candidates


def resolve_title_to_mal(title):
    """Resolve a free-text anime ``title`` to a MAL id via Jikan, or ``None``.

    **Exact-normalized match only** (skip-don't-guess): a candidate counts only when its
    normalized form equals the query's, so a fuzzy near-miss never writes the wrong
    show's status/progress. Result (hit or miss) is cached by normalized title.

    A Jikan outage raises :class:`JikanSearchError` (the ``_jikan_search`` call is left
    uncaught here) so the **miss is never cached** for a transient failure — see the
    class docstring. Callers that don't want it to propagate (``cr_code_to_mal``) catch
    it and return ``None`` without caching.

    Used directly for D3's per-season resolve (each CR season title -> its own MAL id).
    """
    norm = normalize(title)
    if not norm:
        return None

    key = f"cr:resolve:title:{norm}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None  # _MISS ("") -> None

    mal_id = None
    # _jikan_search raises JikanSearchError on an outage; cache.set below is then
    # skipped, so a failed fetch is never persisted as a month-long miss.
    for cand in _jikan_search(title):
        if any(normalize(t) == norm for t in cand["titles"]):
            mal_id = cand["mal_id"]
            break

    cache.set(key, mal_id or _MISS, RESOLVE_CACHE_TTL)
    return mal_id


def cr_code_to_mal(code, title):
    """Resolve a CR series ``code`` (with its ``title``) to a MAL id, or ``None``.

    Seed map first (the maintainer's pre-resolved library, 1:1 and trusted); on a miss,
    the exact-only Jikan fallback via :func:`resolve_title_to_mal`. The per-code outcome
    is cached so the beat resolves each new CR series at most once a month.

    Returns ``None`` for an unresolvable code — the caller (C2/C3) then skips that title
    and counts it for the run summary rather than guessing a MAL id. A Jikan outage is
    *not* an unresolvable code: it returns ``None`` but caches nothing, so the next beat
    retries instead of carrying a manufactured month-long miss.
    """
    seeded = load_cr_mal_map().get(code)
    if seeded:
        return seeded

    key = f"cr:resolve:code:{code}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None

    try:
        mal_id = resolve_title_to_mal(title)
    except JikanSearchError:
        # Transient outage, not a real miss: leave key uncached and let the beat retry.
        logger.warning(
            "Jikan unavailable while resolving %r; %s left uncached", title, key
        )
        return None
    cache.set(key, mal_id or _MISS, RESOLVE_CACHE_TTL)
    return mal_id
