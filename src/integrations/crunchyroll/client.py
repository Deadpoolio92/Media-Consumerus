"""Thin Crunchyroll API client — the single network boundary for the CR integration.

Every CR-specific URL, header, auth detail and response shape lives here, so an
upstream merge or a CR API change touches exactly one file (and tests stub exactly
one function). Mirrors E1's ``app/providers/mydublist.py`` discipline.

**E9a surface (this phase):**
  * :func:`mint_token` — exchange the long-lived ``etp_rt`` cookie for a short-lived
    access token (replaces v1's manual ~3-min paste).
  * :func:`fetch_catalog` — the full ``discover/browse`` catalog (one request).
  * :func:`series` — the ``cms/series/{code}`` fallback for titles missing from browse.

**E9b will add** ``refresh_token``, ``list_profiles`` / ``select_profile`` /
``confirm_profile`` (shared-account guard), ``fetch_watchlist`` and ``fetch_history``.

Locale shape nuance (preserved from v1, covered by tests): ``cms/series/{code}``
returns locales at the **top level** (``.audio_locales``), while ``discover/browse``
nests them under ``.series_metadata`` (or ``.movie_listing_metadata``).
:func:`_extract_locales` walks that fallback chain. Locale values are returned as raw
CR/BCP-47 **codes** (``ja-JP``); ``AnimeAvailability`` stores codes and
``app/languages.py`` maps them to display names.

**Auth is unofficial.** CR's web token endpoint expects a public Basic-auth client
credential (the same value baked into the CR web bundle for every user). It is NOT a
per-user secret, but it is undocumented and can rotate, so it is config
(``settings.CRUNCHYROLL_BASIC_AUTH``), not a hard-coded constant — :func:`_basic_auth`
fails loudly if unset rather than shipping a guessed value. Obtain it once from the
browser (the ``Authorization: Basic ...`` header on the token request); see the runbook.
"""

import logging

import requests
from django.conf import settings

from app.providers import services

logger = logging.getLogger(__name__)

PROVIDER = "crunchyroll"
BASE = "https://www.crunchyroll.com"
TOKEN_URL = f"{BASE}/auth/v1/token"
BROWSE_URL = f"{BASE}/content/v2/discover/browse"
SERIES_URL = f"{BASE}/content/v2/cms/series/{{code}}"
MULTIPROFILE_URL = f"{BASE}/accounts/v1/me/multiprofile"

# v1 sent a desktop-Chrome UA; CR's edge rejects obviously-bot agents.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

# discover/browse caps n per page (a single n=1500 request now 400s "Invalid request
# parameters"), so the catalog is paged. sort_by=alphabetical keeps paging stable; an
# explicit locale is required now that the token carries no implicit browser locale.
CATALOG_PAGE_SIZE = 100
CATALOG_MAX_PAGES = 60  # safety cap (~6000 titles) so a paging bug can't loop forever
CATALOG_LOCALE = "en-US"

# The token endpoint requires device_id + device_type (verified live: omitting them
# returns 400 auth.obtain_access_token.missing_required_field). device_type is a free
# label; device_id should be STABLE across runs (a fresh id per call looks like a new
# device and can trip CR's device limits), so it's a setting with a fixed default.
DEVICE_TYPE = "Chrome on Windows"
DEFAULT_DEVICE_ID = "5a3b9d6e-2c14-4f7a-8e0b-9d1c2a3b4c5d"

# Where browse/cms-series stash locale lists, in fallback order (top-level first so the
# cms/series shape wins; then the two browse nestings).
_LOCALE_PARENTS = ("series_metadata", "movie_listing_metadata")


def _basic_auth():
    """Return the CR web Basic-auth header value, or raise if unconfigured.

    Not a per-user secret (it's the public web-client credential), but undocumented
    and rotatable, so it's required config rather than a guessed in-source default.
    """
    value = getattr(settings, "CRUNCHYROLL_BASIC_AUTH", "")
    if not value:
        msg = (
            "CRUNCHYROLL_BASIC_AUTH is not set. Copy the 'Authorization: Basic ...' "
            "value from a logged-in browser's POST to /auth/v1/token (see the E9 "
            "runbook) and set it in the env/override."
        )
        raise ValueError(msg)
    if not value.lower().startswith("basic "):
        value = f"Basic {value}"
    return value


def _device_id():
    """Return a stable device id for token requests (setting, fixed default)."""
    return getattr(settings, "CRUNCHYROLL_DEVICE_ID", "") or DEFAULT_DEVICE_ID


def _cr_request(method, url, *, params=None, data=None, headers, none_on=()):
    """Call the CR API via the shared session, surfacing the response body on error.

    CR is unofficial: failures explain themselves in the JSON body
    (``{"code": "...", "error": "..."}``), not the status line. On any HTTP error this
    raises ``ValueError`` carrying the status + body, so commands show the real cause
    instead of a bare ``400 Bad Request``. Statuses listed in ``none_on`` return
    ``None`` instead of raising (e.g. a 404 for a series pulled from CR is a skip, not
    an error).
    """
    try:
        return services.api_request(
            PROVIDER,
            method,
            url,
            params=params,
            data=data,
            headers=headers,
        )
    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        if status in none_on:
            return None
        body = exc.response.text[:500] if exc.response is not None else ""
        endpoint = url.split("?", 1)[0]
        msg = f"Crunchyroll {method} {endpoint} failed ({status}): {body}"
        raise ValueError(msg) from exc


def mint_token(etp_rt):
    """Exchange the ``etp_rt`` cookie for a short-lived CR access token (a string).

    POSTs ``grant_type=etp_rt_cookie`` to the token endpoint with the ``etp_rt`` sent
    as a cookie and the public web client as Basic auth. Raises ``ValueError`` if the
    credential is unset or the response carries no ``access_token``; lets
    ``requests`` HTTP/network errors propagate (the backfill aborts cleanly).

    The exact grant/profile mechanics are unofficial and were live-verified at build
    time; if CR changes the flow, this function and the runbook are the only things to
    update.
    """
    headers = {
        "Authorization": _basic_auth(),
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": USER_AGENT,
        "Cookie": f"etp_rt={etp_rt}",
    }
    payload = _cr_request(
        "POST",
        TOKEN_URL,
        data={
            "grant_type": "etp_rt_cookie",
            "device_id": _device_id(),
            "device_type": DEVICE_TYPE,
        },
        headers=headers,
    )
    token = (payload or {}).get("access_token")
    if not token:
        msg = "Crunchyroll token response had no access_token"
        raise ValueError(msg)
    return token


def _auth_headers(token):
    """Bearer headers for catalog/series calls (token from :func:`mint_token`)."""
    return {
        "Authorization": f"Bearer {token}",
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    }


def _extract_locales(node, key):
    """Return ``node``'s ``key`` locale list, walking the top-level→nested fallback.

    ``key`` is ``"audio_locales"`` or ``"subtitle_locales"``. Handles both the
    cms/series shape (top-level) and the browse shape (nested under
    ``series_metadata`` / ``movie_listing_metadata``). Always returns a list.
    """
    if not isinstance(node, dict):
        return []
    if node.get(key):
        return node[key]
    for parent in _LOCALE_PARENTS:
        meta = node.get(parent)
        if isinstance(meta, dict) and meta.get(key):
            return meta[key]
    return []


def _parse_entry(entry):
    """Normalize one browse entry to a ``{code, title, type, *_locales}`` dict."""
    return {
        "code": entry.get("id"),
        "title": entry.get("title", ""),
        "type": entry.get("type", ""),
        "audio_locales": _extract_locales(entry, "audio_locales"),
        "subtitle_locales": _extract_locales(entry, "subtitle_locales"),
    }


def fetch_catalog(token):
    """Return the full CR browse catalog as normalized entries (paged).

    Pages ``discover/browse`` at ``CATALOG_PAGE_SIZE`` until a short/empty page (or the
    ``CATALOG_MAX_PAGES`` safety cap). Each entry is
    ``{code, title, type, audio_locales, subtitle_locales}`` with locale **codes**;
    entries without an ``id`` are dropped. HTTP/network errors surface via
    :func:`_cr_request`.
    """
    headers = _auth_headers(token)
    raw = []
    start = 0
    for _ in range(CATALOG_MAX_PAGES):
        payload = _cr_request(
            "GET",
            BROWSE_URL,
            params={
                "start": start,
                "n": CATALOG_PAGE_SIZE,
                "sort_by": "alphabetical",
                "locale": CATALOG_LOCALE,
            },
            headers=headers,
        )
        page = (payload or {}).get("data") or []
        raw.extend(page)
        if len(page) < CATALOG_PAGE_SIZE:
            break  # last (or empty) page
        start += CATALOG_PAGE_SIZE
    return [_parse_entry(e) for e in raw if e.get("id")]


def series(token, code):
    """Return audio/subtitle locale lists for a CR series ``code``, or ``None``.

    The ``cms/series/{code}`` fallback for titles absent from the bulk browse catalog.
    A 404 (a stale seed code for a series no longer on CR) or an empty payload yields
    ``None`` — a clean skip, not an error. Other HTTP errors surface via
    :func:`_cr_request` and the backfill's per-item guard counts them.
    """
    payload = _cr_request(
        "GET",
        SERIES_URL.format(code=code),
        headers=_auth_headers(token),
        none_on=(404,),
    )
    data = (payload or {}).get("data") or []
    if not data:
        return None
    node = data[0]
    return {
        "audio_locales": _extract_locales(node, "audio_locales"),
        "subtitle_locales": _extract_locales(node, "subtitle_locales"),
    }


def list_profiles(token):
    """Return the shared account's CR profiles (read-only ``multiprofile`` GET).

    Each profile is ``{profile_id, profile_name, is_primary, is_selected, …}``. E9a
    doesn't need a profile (C1 is catalog-wide), but this lets the maintainer discover
    their ``CRUNCHYROLL_PROFILE_ID`` early and verifies the token + endpoint shape ahead
    of E9b. The profile **switch** mechanism (select/confirm, the guard) lands in E9b.
    """
    payload = _cr_request("GET", MULTIPROFILE_URL, headers=_auth_headers(token))
    return (payload or {}).get("profiles") or []
