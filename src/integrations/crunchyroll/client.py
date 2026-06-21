"""Thin Crunchyroll API client — the single network boundary for the CR integration.

Every CR-specific URL, header, auth detail and response shape lives here, so an
upstream merge or a CR API change touches exactly one file (and tests stub exactly
one function). Mirrors E1's ``app/providers/mydublist.py`` discipline.

**E9a surface (this phase):**
  * :func:`mint_token` — exchange the long-lived ``etp_rt`` cookie for a short-lived
    access token (replaces v1's manual ~3-min paste).
  * :func:`fetch_catalog` — the full ``discover/browse`` catalog (one request).
  * :func:`series` — the ``cms/series/{code}`` fallback for titles missing from browse.

**E9b surface (added):** :func:`account_id` (the watchlist/history path segment),
profile binding via ``mint_token(..., profile_id=…)`` + :func:`confirm_profile` (the
shared-account guard), :func:`fetch_watchlist`, :func:`fetch_history`, and
:func:`seasons` (the per-season CR→MAL resolve for multi-season franchises, D3).

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
SEASONS_URL = f"{BASE}/content/v2/cms/series/{{code}}/seasons"
MULTIPROFILE_URL = f"{BASE}/accounts/v1/me/multiprofile"
ME_URL = f"{BASE}/accounts/v1/me"
# Watchlist (C2) + history (C3) are account-scoped; the access token's bound profile
# (see mint_token's profile_id) decides which person's data the account path returns.
WATCHLIST_URL = f"{BASE}/content/v2/discover/{{account}}/watchlist"
HISTORY_URL = f"{BASE}/content/v2/{{account}}/watch-history"

# watch-history is grabbed in one large page (v1 used page_size=1000); a personal
# account never approaches this, and C3 only needs the furthest episode per series.
HISTORY_PAGE_SIZE = 1000
WATCHLIST_PAGE_SIZE = 500

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


def mint_token(etp_rt, profile_id=None):
    """Exchange the ``etp_rt`` cookie for a short-lived CR access token (a string).

    POSTs ``grant_type=etp_rt_cookie`` to the token endpoint with the ``etp_rt`` sent
    as a cookie and the public web client as Basic auth. Raises ``ValueError`` if the
    credential is unset or the response carries no ``access_token``; lets
    ``requests`` HTTP/network errors propagate (the backfill aborts cleanly).

    ``profile_id`` (E9b): the CR account is shared, so watchlist/history must be read
    as a *specific* profile. The token is bound to a profile **at mint time** (the
    account-scoped paths carry no profile param), so when ``profile_id`` is given it is
    sent as an extra ``profile_id`` form field on the grant. This profile-bind field is
    the **one unofficial mechanism that must be live-verified** (it may instead need a
    dedicated switch endpoint); :func:`confirm_profile` is the mandatory guard that
    catches a bind that silently didn't take. E9a (catalog-wide C1) passes no
    ``profile_id`` and is unaffected.

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
    data = {
        "grant_type": "etp_rt_cookie",
        "device_id": _device_id(),
        "device_type": DEVICE_TYPE,
    }
    if profile_id:
        data["profile_id"] = profile_id
    payload = _cr_request("POST", TOKEN_URL, data=data, headers=headers)
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


# --------------------------------------------------------------------------- #
# E9b: account scope, profile guard, watchlist/history, per-season resolve
# --------------------------------------------------------------------------- #


def account_id(token):
    """Return the CR ``account_id`` for the token (the watchlist/history path segment).

    ``accounts/v1/me`` echoes the account the token authenticates as; v1 keyed every
    user call off this id. Raises ``ValueError`` if the response carries no id.
    """
    payload = _cr_request("GET", ME_URL, headers=_auth_headers(token))
    acct = (payload or {}).get("account_id")
    if not acct:
        msg = "Crunchyroll /accounts/v1/me response had no account_id"
        raise ValueError(msg)
    return acct


def confirm_profile(token, expected_profile_id):
    """Return ``True`` iff the token's *selected* profile is ``expected_profile_id``.

    The mandatory shared-account guard (D-scope): before any C2/C3 write, confirm the
    minted token actually resolved to the maintainer's profile and not the account's
    primary (someone else's). Reads ``multiprofile`` and matches the ``is_selected``
    profile. A blank ``expected_profile_id``, no selected profile, or a mismatch all
    return ``False`` — the caller then skips the write rather than guessing.
    """
    if not expected_profile_id:
        return False
    for profile in list_profiles(token):
        if profile.get("is_selected"):
            return profile.get("profile_id") == expected_profile_id
    return False


def _panel_series_id(panel):
    """Extract a CR series id from a watchlist/history ``panel``, or ``None``.

    Anime live as ``episode`` panels (``episode_metadata.series_id``) or ``series``
    panels (the panel ``id`` itself). Movies (``movie_listing_metadata``) are out of
    anime scope and yield ``None`` (skipped by the caller).
    """
    if not isinstance(panel, dict):
        return None
    episode_meta = panel.get("episode_metadata") or {}
    series_id = episode_meta.get("series_id")
    if series_id:
        return series_id
    if panel.get("type") == "series":
        return panel.get("id")
    return None


def _panel_title(panel):
    """Best series title from a panel (episode's series_title, else the panel title)."""
    episode_meta = (panel or {}).get("episode_metadata") or {}
    return episode_meta.get("series_title") or (panel or {}).get("title") or ""


def fetch_watchlist(token, account):
    """Return watchlist entries as ``[{series_id, title}]`` (anime series only).

    ``discover/{account}/watchlist`` newest-first; one page of ``WATCHLIST_PAGE_SIZE``
    (a personal watchlist never approaches it). Entries without a resolvable series id
    (movies, malformed panels) are dropped. The account's *bound profile* (mint-time)
    decides whose watchlist this is — guard with :func:`confirm_profile` first.
    """
    payload = _cr_request(
        "GET",
        WATCHLIST_URL.format(account=account),
        params={"order": "desc", "n": WATCHLIST_PAGE_SIZE},
        headers=_auth_headers(token),
    )
    entries = []
    for row in (payload or {}).get("data") or []:
        panel = row.get("panel") or row
        series_id = _panel_series_id(panel)
        if series_id:
            entries.append({"series_id": series_id, "title": _panel_title(panel)})
    return entries


def _parse_history_row(row):
    """Normalize one watch-history row to a progress dict, or ``None`` (no series id).

    Returns ``{series_id, season_number, episode_number, title}``. Fields may sit on the
    row itself or under ``panel.episode_metadata`` depending on CR's shape; both are
    checked. Season/episode default to 1/0 when absent.
    """
    panel = row.get("panel") or {}
    episode_meta = panel.get("episode_metadata") or {}
    series_id = row.get("series_id") or episode_meta.get("series_id")
    if not series_id:
        return None
    return {
        "series_id": series_id,
        "season_number": row.get("season_number")
        or episode_meta.get("season_number")
        or 1,
        "episode_number": row.get("episode_number")
        or episode_meta.get("episode_number")
        or 0,
        "title": _panel_title(panel) or row.get("series_title") or "",
    }


def fetch_history(token, account):
    """Return normalized watch-history rows (one per played episode CR records).

    Each row is ``{series_id, season_number, episode_number, title}``.
    ``{account}/watch-history`` in one ``HISTORY_PAGE_SIZE`` page (matches v1; ample for
    a personal account). Rows without a series id are dropped. C3 keeps the furthest
    episode per (series, season) — this returns the raw rows; the caller aggregates.
    """
    payload = _cr_request(
        "GET",
        HISTORY_URL.format(account=account),
        params={"page_size": HISTORY_PAGE_SIZE},
        headers=_auth_headers(token),
    )
    rows = []
    for row in (payload or {}).get("data") or []:
        parsed = _parse_history_row(row)
        if parsed:
            rows.append(parsed)
    return rows


def seasons(token, code):
    """Return a series' seasons as ``[{season_number, title}]``, or ``[]`` (for D3).

    ``cms/series/{code}/seasons`` lists each CR season with its own title; C3 maps a
    multi-season history row's ``season_number`` to the matching season title, then
    resolves that title to its own MAL id. A 404/empty payload yields ``[]`` (the
    caller falls back to skip + report).
    """
    payload = _cr_request(
        "GET",
        SEASONS_URL.format(code=code),
        headers=_auth_headers(token),
        none_on=(404,),
    )
    return [
        {"season_number": node.get("season_number"), "title": node.get("title", "")}
        for node in (payload or {}).get("data") or []
    ]
