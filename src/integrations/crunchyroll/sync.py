"""Crunchyroll sync orchestrator.

**E9a (this phase):** :func:`backfill_c1` — a one-off, library-only dub/sub backfill
into E1's ``AnimeAvailability``. Read-only on CR, profile-independent.

**E9b (deferred):** C2 watchlist -> status and C3 history -> progress (with the
CR->MAL resolver, multi-season handling, and the shared-account profile guard).

Data flow (E9a)::

    fetch_catalog(token)            # ONE request (D7)
        │  build by_code + by_title indexes (in-memory, O(1))
        ▼
    for each library MAL anime Item:
        code = mal_to_cr[item.media_id]      # seed map (D6: seed first)
        entry = by_code[code]  OR  by_title[norm(title)]   # exact-title fallback (D6)
        entry?  ── yes ─► use its locales
                ── no, but have code ─► client.series(code)   # cms, misses only (D7)
                ── no, no code ─► skip + count
        ▼
    upsert_availability(item, audio=…or None, subtitle=…or None, source=crunchyroll)
        # no-blank: empty CR list -> None -> field left untouched (D2 write rules)
"""

import logging

from app.models import AvailabilitySource, Item, MediaTypes, Sources
from app.tasks import upsert_availability
from integrations.crunchyroll import client, resolve

logger = logging.getLogger(__name__)


def _norm_title(title):
    """Normalize a title for matching: casefold + collapse whitespace."""
    return " ".join((title or "").split()).casefold()


def backfill_c1(token):
    """Backfill dub/sub for every library anime from the CR catalog; return a summary.

    ``token`` is an access token from :func:`client.mint_token`. Library-only: iterates
    tracked MAL anime ``Item`` rows and never adds new items. Matching is seed-code
    first, then an EXACT normalized-title fallback, else skip (D6); a seed-coded title
    absent from the bulk catalog falls back to one ``cms/series`` call (D7). Writes go
    through the shared ``upsert_availability`` (no-blank, last-write-wins; D2/D4). One
    failing title is counted and skipped, never fatal.

    Returns a counts dict: ``library`` (anime seen), ``written``, ``unchanged``,
    ``unmatched``, ``errors``, plus per-route hits (``via_seed`` / ``via_title`` /
    ``via_series``).
    """
    catalog = client.fetch_catalog(token)
    by_code = {e["code"]: e for e in catalog if e.get("code")}
    by_title = {}
    for e in catalog:
        key = _norm_title(e.get("title"))
        if key:
            by_title.setdefault(key, e)  # first-wins on duplicate titles

    mal_to_cr = resolve.mal_to_cr()

    counts = {
        "library": 0,
        "written": 0,
        "unchanged": 0,
        "unmatched": 0,
        "errors": 0,
        "via_seed": 0,
        "via_title": 0,
        "via_series": 0,
    }

    anime_items = Item.objects.filter(
        media_type=MediaTypes.ANIME.value,
        source=Sources.MAL.value,
    )
    for item in anime_items.iterator():
        counts["library"] += 1
        try:
            locales = _resolve_locales(
                token, item, by_code, by_title, mal_to_cr, counts,
            )
            if locales is None:
                counts["unmatched"] += 1
                continue
            audio, subtitle = locales
            written = upsert_availability(
                item,
                audio=audio or None,  # empty -> None: never blank (D2)
                subtitle=subtitle or None,
                source=AvailabilitySource.CRUNCHYROLL.value,
            )
            counts["written" if written else "unchanged"] += 1
        except Exception:
            counts["errors"] += 1
            logger.exception(
                "CR backfill failed for item %s (%s)", item.media_id, item.title,
            )

    logger.info(
        "CR C1 backfill: %s/%s written (%s unchanged, %s unmatched, %s errors)",
        counts["written"],
        counts["library"],
        counts["unchanged"],
        counts["unmatched"],
        counts["errors"],
    )
    return counts


def _resolve_locales(token, item, by_code, by_title, mal_to_cr, counts):
    """Return ``(audio, subtitle)`` code lists for one item, or ``None`` if unmatched.

    Match order (D6): seed code in the bulk catalog -> exact normalized-title in the
    bulk catalog -> (seed code only) one cms/series fallback (D7) -> unmatched.
    """
    code = mal_to_cr.get(item.media_id)

    entry = by_code.get(code) if code else None
    if entry is not None:
        counts["via_seed"] += 1
        return entry["audio_locales"], entry["subtitle_locales"]

    entry = by_title.get(_norm_title(item.title))
    if entry is not None:
        counts["via_title"] += 1
        return entry["audio_locales"], entry["subtitle_locales"]

    if code:
        detail = client.series(token, code)  # cms/series fallback — misses only (D7)
        if detail is not None:
            counts["via_series"] += 1
            return detail["audio_locales"], detail["subtitle_locales"]

    return None
