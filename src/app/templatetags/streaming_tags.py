"""Template tags for streaming "where to watch" links (E6).

Kept in a dedicated module (not app_tags.py) so an upstream merge never collides with
Yamtrack's own template tags -- and so E6 needs **zero** edits to upstream's views or
providers: the detail view already passes ``media.providers`` plus the user's region
into the template, and these tags derive the links from there.

Two links, both gated by ``settings.STREAMING_LINKS_ENABLED`` (off reverts to stock
rendering: unlinked logos, no Crunchyroll card):

* :func:`region_watch_link` -- the JustWatch aggregator URL TMDB returns at
  ``providers[region].link`` (the only link the watch/providers API gives; per-provider
  / per-episode deep links are not available). Wraps the tv/movie/season logos.
* :func:`crunchyroll_url` -- a Crunchyroll series deep-link for MAL-sourced anime,
  built from the E9a CR<->MAL seed map. Anime skip TMDB watch-providers, so this is
  their streaming link.
"""

from django import template
from django.conf import settings

from app.models import MediaTypes, Sources, StreamingLink
from integrations.crunchyroll.resolve import series_url as cr_series_url

register = template.Library()

# Media types that get the "where to watch" treatment (auto links + manual links).
# Books/manga/games are excluded — games get their own E7 "play links" later.
STREAMABLE_TYPES = frozenset(
    {
        MediaTypes.ANIME.value,
        MediaTypes.TV.value,
        MediaTypes.MOVIE.value,
        MediaTypes.SEASON.value,
    },
)


def _enabled():
    """Whether E6 streaming links are turned on (default True)."""
    return getattr(settings, "STREAMING_LINKS_ENABLED", True)


@register.simple_tag
def is_streamable(media_type):
    """Whether a media type shows the STREAMING card (so links can be added to it)."""
    return media_type in STREAMABLE_TYPES


@register.simple_tag
def manual_streaming_links(media_id, source, media_type, season_number=None):
    """Return the user-added :class:`StreamingLink` rows for a title (E6).

    Title-level: filtered by the item's identity (media_id/source/media_type and, for
    a season, its season_number). Empty/absent ``season_number`` (non-season types)
    normalizes to ``None``. Ordered oldest-first by the model's ``Meta.ordering``.
    """
    season = season_number if season_number not in ("", None) else None
    return StreamingLink.objects.filter(
        item__media_id=str(media_id),
        item__source=source,
        item__media_type=media_type,
        item__season_number=season,
    )


@register.simple_tag
def region_watch_link(providers, region):
    """Return the JustWatch "where to watch" URL for the user's region, or ``""``.

    ``providers`` is TMDB's raw ``watch/providers`` results dict (``media.providers``);
    ``providers[region].link`` is JustWatch's aggregator page for this title+region, the
    single link TMDB exposes. ``""`` when disabled, region-unset, or no link is present.
    """
    if not _enabled() or not providers or region in ("", "UNSET", None):
        return ""
    return (providers.get(region) or {}).get("link", "") or ""


@register.simple_tag
def crunchyroll_url(media_id, source, media_type):
    """Return a Crunchyroll series deep-link for a MAL-sourced anime, or ``""``.

    Gated to ``media_type == anime`` and ``source == mal`` (the seed is MAL-keyed;
    AniList-sourced anime are skipped). A seed miss yields ``""`` — no guessing a code.
    """
    if not _enabled():
        return ""
    if media_type != MediaTypes.ANIME.value or source != Sources.MAL.value:
        return ""
    return cr_series_url(media_id) or ""
