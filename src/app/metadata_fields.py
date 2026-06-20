"""Extract filterable catalog facts (genre + year) from provider metadata.

Genre and release year aren't stored on ``Item`` — they only exist in the live
provider metadata dict returned by ``providers.services.get_media_metadata``. E2
denormalizes them into ``ItemMetadata`` so the list view can filter on them; this
module is the single place that knows how to pull them out of that dict.

The pure extractors (``genres_from`` / ``year_from``) are offline-testable. Only
``fetch_for_item`` touches the network — it is the network boundary the test
suite stubs (the E1 ``mydublist.get_locales`` role), so the broad suite stays
offline by patching this one symbol.
"""

import re

from app.models import MediaTypes
from app.providers import services

# Which media types get an ``ItemMetadata`` row / a genre+year filter. These are
# the list views the maintainer filters (the product-scope types + season, whose
# own list view is used for TV tracking). Episode/manga/comic/book/boardgame are
# out of scope. Shared by the on-add signal and the daily sync.
FILTERABLE_MEDIA_TYPES = (
    MediaTypes.MOVIE.value,
    MediaTypes.TV.value,
    MediaTypes.SEASON.value,
    MediaTypes.ANIME.value,
    MediaTypes.GAME.value,
)

# ``details`` keys that hold the item's own release/air/start date, in priority
# order. Movies/games use ``release_date``, TV/seasons ``first_air_date``,
# anime/manga ``start_date`` — only one is present per metadata dict.
_DATE_KEYS = ("release_date", "first_air_date", "start_date")
_YEAR_RE = re.compile(r"(\d{4})")


def genres_from(metadata):
    """Return the genre name list from a provider metadata dict (never ``None``).

    Providers return ``genres`` as a list of name strings, or ``None`` when the
    catalog has no genres — normalize both to a list.
    """
    return metadata.get("genres") or []


def year_from(metadata):
    """Return the release year (int) from a provider metadata dict, or ``None``.

    Reads the item's own date from ``details`` (the first present of
    ``release_date`` / ``first_air_date`` / ``start_date``) and takes its leading
    4-digit year. Tolerates partial dates (MAL emits ``"2009"`` / ``"2009-04"``)
    and missing/empty values.
    """
    details = metadata.get("details") or {}
    for key in _DATE_KEYS:
        value = details.get(key)
        if not value:
            continue
        match = _YEAR_RE.search(str(value))
        if match:
            return int(match.group(1))
    return None


def fetch_for_item(item):
    """Fetch genre + year for one ``Item`` from its catalog provider.

    Returns ``{"genres": [...], "release_year": int | None}``, or ``None`` when
    the provider yields neither (so callers skip writing an empty row). Hits the
    metadata cache populated by the normal track/detail flows, so this is cheap.
    Network/parse errors propagate to the caller, which swallows them.
    """
    season_numbers = (
        [item.season_number]
        if item.media_type == MediaTypes.SEASON.value
        else None
    )
    metadata = services.get_media_metadata(
        item.media_type,
        item.media_id,
        item.source,
        season_numbers,
    )
    genres = genres_from(metadata)
    release_year = year_from(metadata)
    if not genres and release_year is None:
        return None
    return {"genres": genres, "release_year": release_year}
