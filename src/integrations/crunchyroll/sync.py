"""Crunchyroll sync orchestrator.

**E9a:** :func:`backfill_c1` — a one-off, library-only dub/sub backfill into E1's
``AnimeAvailability``. Read-only on CR, profile-independent.

**E9b:** :func:`sync_c2_status` (watchlist -> status) and :func:`sync_c3_progress`
(history -> progress), driven by the daily beat in ``integrations/tasks.py``. Both take
a ``user`` and a token the caller **already profile-confirmed** (the shared-account
guard lives in the task, not here). Writes are conservative and user-respecting:

  * **never downgrade** ``Completed`` and never touch a ``Paused``/``Dropped`` row
    (those are manual intent — mirror of the webhook's never-overwrite stance);
  * **forward-only** progress (a furthest-episode write never reduces progress);
  * C2 only *creates* ``Planning`` rows for untracked watchlist titles; the In-progress
    / Completed transition is driven solely by C3's real progress (plan's C2 rule);
  * an unresolvable CR series is **skipped + counted**, never guess-written.

**D3 multi-season (hybrid):** season-1 history maps off the seed
(:func:`resolve.cr_code_to_mal`); a season>1 row is resolved per-season via
``client.seasons`` + :func:`resolve.resolve_title_to_mal` (exact-only), falling back to
**skip + report** when that season title can't be matched — so the ~16 known franchises
auto-track when CR's season title resolves cleanly, else surface for manual handling.

The shared advancement rule (:func:`_advance_progress`) is a self-contained
re-implementation of the webhook's forward-only/never-downgrade logic — deliberately NOT
a refactor of ``webhooks/anime.py._handle_anime`` (that file is webhook-coupled *and*
under active upstream rework on ``harshil/fix-rewatch-tracking``; editing it would
invite merge conflicts, against the fork's prime directive).

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

from django.utils import timezone

from app.mixins import disable_fetch_releases
from app.models import (
    Anime,
    AvailabilitySource,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from app.providers import services
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


# --------------------------------------------------------------------------- #
# E9b — C2 watchlist -> status, C3 history -> progress
# --------------------------------------------------------------------------- #


def _anime_metadata(mal_id):
    """Catalog metadata (title/image/max_progress) for a MAL anime id (cached)."""
    return services.get_media_metadata(
        MediaTypes.ANIME.value,
        mal_id,
        Sources.MAL.value,
    )


def _get_or_create_item(mal_id):
    """Return the ``Item`` for a MAL anime id, creating it from catalog metadata if new.

    Forward tracking can encounter a CR title the library never had; we materialize the
    catalog ``Item`` (title/image from the provider) so a tracked ``Anime`` row can hang
    off it — exactly as the webhook does for a freshly-played anime.
    """
    item = Item.objects.filter(
        media_id=mal_id,
        source=Sources.MAL.value,
        media_type=MediaTypes.ANIME.value,
    ).first()
    if item is not None:
        return item
    meta = _anime_metadata(mal_id)
    return Item.objects.create(
        media_id=mal_id,
        source=Sources.MAL.value,
        media_type=MediaTypes.ANIME.value,
        title=meta["title"],
        image=meta["image"],
    )


def _advance_progress(user, item, furthest):
    """Forward-only progress write for one anime; return the outcome label.

    The shared advancement rule (see module docstring); returns
    ``written``/``unchanged``/``skipped``. Never reduces progress, never downgrades
    ``Completed``, and leaves a ``Paused``/``Dropped`` row untouched. A new row is
    created ``In progress`` (or ``Completed`` at the episode count) only with progress.
    """
    max_progress = _anime_metadata(item.media_id).get("max_progress")
    capped = min(furthest, max_progress) if max_progress else furthest
    is_completed = bool(max_progress) and furthest >= max_progress
    now = timezone.now().replace(second=0, microsecond=0)

    existing = Anime.objects.filter(item=item, user=user).first()
    if existing is None:
        if furthest <= 0:
            return "skipped"
        Anime.objects.create(
            item=item,
            user=user,
            progress=capped,
            status=Status.COMPLETED.value if is_completed else Status.IN_PROGRESS.value,
            start_date=None if is_completed else now,
            end_date=now if is_completed else None,
        )
        return "written"

    # Terminal/manual states are user-owned — never auto-change them.
    if existing.status in (
        Status.COMPLETED.value,
        Status.PAUSED.value,
        Status.DROPPED.value,
    ):
        return "skipped"

    # Planning or In progress: advance forward-only.
    existing.progress = max(existing.progress, capped)
    if is_completed:
        existing.status = Status.COMPLETED.value
        existing.end_date = now
    elif existing.status == Status.PLANNING.value:
        existing.status = Status.IN_PROGRESS.value
        existing.start_date = existing.start_date or now

    if existing.tracker.changed():
        existing.save()
        return "written"
    return "unchanged"


def sync_c2_status(token, account, user):
    """C2: ensure every watchlist title is at least ``Planning`` for ``user``.

    Watchlist membership means "plan to watch": an untracked title gets a fresh
    ``Planning`` row. An already-tracked title is left untouched here — C3's real
    progress is the only thing that promotes a row to In progress/Completed (plan's C2
    rule). An unresolvable CR series is counted as ``unmatched`` and skipped.

    ``token`` must already be profile-confirmed by the caller. Returns a counts dict.
    """
    counts = {"watchlist": 0, "planning_created": 0, "skipped": 0, "unmatched": 0,
              "errors": 0}
    with disable_fetch_releases():
        for entry in client.fetch_watchlist(token, account):
            counts["watchlist"] += 1
            try:
                mal_id = resolve.cr_code_to_mal(entry["series_id"], entry["title"])
                if not mal_id:
                    counts["unmatched"] += 1
                    continue
                item = _get_or_create_item(mal_id)
                if Anime.objects.filter(item=item, user=user).exists():
                    counts["skipped"] += 1  # tracked already — C3 drives transitions
                    continue
                Anime.objects.create(
                    item=item,
                    user=user,
                    status=Status.PLANNING.value,
                    progress=0,
                )
                counts["planning_created"] += 1
            except Exception:
                counts["errors"] += 1
                logger.exception("CR C2 failed for series %s", entry.get("series_id"))
    logger.info(
        "CR C2 watchlist: %s planning created, %s already tracked, %s unmatched, "
        "%s errors (of %s)",
        counts["planning_created"], counts["skipped"], counts["unmatched"],
        counts["errors"], counts["watchlist"],
    )
    return counts


def _season_title(token, series_id, season_number):
    """Return the CR title of ``season_number`` within ``series_id``, or ``None``."""
    for season in client.seasons(token, series_id):
        if season.get("season_number") == season_number:
            return season.get("title")
    return None


def _resolve_history_target(token, series_id, season_number, series_title, counts):
    """Resolve one (series, season) history key to a MAL id, or ``None`` (D3 hybrid).

    Season 1 maps off the seed (the franchise's primary MAL entry). A season>1 row is
    resolved per-season via ``client.seasons`` + the exact-only title resolver; an
    unresolvable higher season is counted ``multi_season_skipped`` and skipped.
    """
    if season_number == 1:
        mal_id = resolve.cr_code_to_mal(series_id, series_title)
        if not mal_id:
            counts["unmatched"] += 1
        return mal_id

    season_title = _season_title(token, series_id, season_number)
    mal_id = resolve.resolve_title_to_mal(season_title) if season_title else None
    if mal_id:
        counts["via_season"] += 1
        return mal_id
    counts["multi_season_skipped"] += 1
    logger.info(
        "CR C3: multi-season %r S%s unresolved -> skipped (report)",
        series_title, season_number,
    )
    return None


def sync_c3_progress(token, account, user):
    """C3: write furthest-watched progress per resolved MAL anime for ``user``.

    Aggregates watch-history to the furthest episode per (series, season), resolves each
    to a MAL id (D3 hybrid), and applies the forward-only rule. Multi-season rows that
    don't resolve are reported (``multi_season_skipped``), never guess-written.

    ``token`` must already be profile-confirmed by the caller. Returns a counts dict.
    """
    counts = {"series": 0, "written": 0, "unchanged": 0, "skipped": 0, "unmatched": 0,
              "via_season": 0, "multi_season_skipped": 0, "errors": 0}

    furthest = {}  # (series_id, season_number) -> max episode
    titles = {}  # series_id -> series title
    for row in client.fetch_history(token, account):
        key = (row["series_id"], row["season_number"])
        furthest[key] = max(furthest.get(key, 0), row["episode_number"])
        titles.setdefault(row["series_id"], row["title"])

    with disable_fetch_releases():
        for (series_id, season_number), episode in furthest.items():
            counts["series"] += 1
            try:
                mal_id = _resolve_history_target(
                    token, series_id, season_number, titles[series_id], counts,
                )
                if not mal_id:
                    continue
                item = _get_or_create_item(mal_id)
                counts[_advance_progress(user, item, episode)] += 1
            except Exception:
                counts["errors"] += 1
                logger.exception("CR C3 failed for series %s", series_id)

    logger.info(
        "CR C3 history: %s written, %s unchanged, %s skipped, %s unmatched, "
        "%s via-season, %s multi-season-skipped, %s errors (of %s series/season keys)",
        counts["written"], counts["unchanged"], counts["skipped"], counts["unmatched"],
        counts["via_season"], counts["multi_season_skipped"], counts["errors"],
        counts["series"],
    )
    return counts
