"""Unit tests for the E6 streaming-link template tags."""

from django.test import SimpleTestCase, TestCase, override_settings

from app.models import Item, MediaTypes, Sources, StreamingLink
from app.templatetags import streaming_tags

JUSTWATCH = "https://www.themoviedb.org/movie/238/watch?locale=US"
PROVIDERS = {
    "US": {"link": JUSTWATCH, "flatrate": [{"provider_name": "Netflix"}]},
    "GB": {"link": "https://example.com/gb"},
}


class RegionWatchLinkTests(SimpleTestCase):
    """region_watch_link — the per-region JustWatch aggregator URL."""

    def test_returns_link_for_region(self):
        """The region's JustWatch link is returned verbatim."""
        self.assertEqual(streaming_tags.region_watch_link(PROVIDERS, "US"), JUSTWATCH)

    def test_unset_region_returns_empty(self):
        """The sentinel 'UNSET' (region preference unset) yields ''."""
        self.assertEqual(streaming_tags.region_watch_link(PROVIDERS, "UNSET"), "")

    def test_disabled_region_returns_empty(self):
        """'' (feature disabled in preferences) yields ''."""
        self.assertEqual(streaming_tags.region_watch_link(PROVIDERS, ""), "")

    def test_region_without_link_returns_empty(self):
        """A region present but carrying no 'link' key yields ''."""
        self.assertEqual(
            streaming_tags.region_watch_link({"US": {"flatrate": []}}, "US"), ""
        )

    def test_missing_region_returns_empty(self):
        """A region not in the providers dict yields ''."""
        self.assertEqual(streaming_tags.region_watch_link(PROVIDERS, "FR"), "")

    def test_no_providers_returns_empty(self):
        """None/empty providers (non-tv/movie types) yields ''."""
        self.assertEqual(streaming_tags.region_watch_link(None, "US"), "")

    @override_settings(STREAMING_LINKS_ENABLED=False)
    def test_flag_off_returns_empty(self):
        """With the feature flag off, no link is produced."""
        self.assertEqual(streaming_tags.region_watch_link(PROVIDERS, "US"), "")


class CrunchyrollUrlTests(SimpleTestCase):
    """crunchyroll_url — the CR series deep-link for MAL-sourced anime."""

    def test_anime_seed_hit_returns_url(self):
        """A seeded MAL anime resolves to its /series/{code} URL."""
        self.assertEqual(
            streaming_tags.crunchyroll_url(
                "51553", Sources.MAL.value, MediaTypes.ANIME.value
            ),
            "https://www.crunchyroll.com/series/GT00258001",
        )

    def test_non_anime_returns_empty(self):
        """tv/movie (TMDB) never gets a CR link, even from a MAL source value."""
        self.assertEqual(
            streaming_tags.crunchyroll_url(
                "51553", Sources.MAL.value, MediaTypes.MOVIE.value
            ),
            "",
        )

    def test_non_mal_source_returns_empty(self):
        """AniList-sourced anime are skipped (the seed is MAL-keyed)."""
        self.assertEqual(
            streaming_tags.crunchyroll_url("51553", "anilist", MediaTypes.ANIME.value),
            "",
        )

    def test_seed_miss_returns_empty(self):
        """An anime with no seed entry yields '' (no guessing a code)."""
        self.assertEqual(
            streaming_tags.crunchyroll_url(
                "999999999", Sources.MAL.value, MediaTypes.ANIME.value
            ),
            "",
        )

    @override_settings(STREAMING_LINKS_ENABLED=False)
    def test_flag_off_returns_empty(self):
        """With the feature flag off, no CR link is produced."""
        self.assertEqual(
            streaming_tags.crunchyroll_url(
                "51553", Sources.MAL.value, MediaTypes.ANIME.value
            ),
            "",
        )


class IsStreamableTests(SimpleTestCase):
    """is_streamable — which media types get the STREAMING card."""

    def test_video_types_are_streamable(self):
        """Video types (anime/tv/movie/season) are streamable."""
        for media_type in ("anime", "tv", "movie", "season"):
            self.assertTrue(streaming_tags.is_streamable(media_type))

    def test_other_types_are_not_streamable(self):
        """Books/manga/games are not streamable (games get E7 later)."""
        for media_type in ("book", "manga", "game"):
            self.assertFalse(streaming_tags.is_streamable(media_type))


class ManualStreamingLinksTests(TestCase):
    """manual_streaming_links — the user-added links for a title."""

    def setUp(self):
        """Create a movie with two links and a season with its own link."""
        self.movie = Item.objects.create(
            media_id="238",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="The Godfather",
            image="http://example.com/i.jpg",
        )
        StreamingLink.objects.create(item=self.movie, name="Netflix", url="https://nf")
        StreamingLink.objects.create(item=self.movie, name="Hulu", url="https://hulu")
        self.season = Item.objects.create(
            media_id="67116",
            source=Sources.TMDB.value,
            media_type=MediaTypes.SEASON.value,
            season_number=2,
            title="Lethal Weapon S2",
            image="http://example.com/s.jpg",
        )
        StreamingLink.objects.create(item=self.season, name="Disney", url="https://d")

    def test_returns_links_for_title(self):
        """All links for a non-season title come back, ordered oldest-first."""
        links = streaming_tags.manual_streaming_links(
            "238", Sources.TMDB.value, MediaTypes.MOVIE.value
        )
        self.assertEqual([link.name for link in links], ["Netflix", "Hulu"])

    def test_accepts_int_media_id(self):
        """media_id from the metadata dict may be an int; it's coerced to str."""
        links = streaming_tags.manual_streaming_links(
            238, Sources.TMDB.value, MediaTypes.MOVIE.value
        )
        self.assertEqual(links.count(), 2)

    def test_no_links_returns_empty_queryset(self):
        """A title with no links yields an empty queryset."""
        links = streaming_tags.manual_streaming_links(
            "999", Sources.TMDB.value, MediaTypes.MOVIE.value
        )
        self.assertEqual(links.count(), 0)

    def test_season_links_are_scoped_by_season_number(self):
        """A season's links are filtered by its season_number."""
        links = streaming_tags.manual_streaming_links(
            "67116", Sources.TMDB.value, MediaTypes.SEASON.value, 2
        )
        self.assertEqual([link.name for link in links], ["Disney"])

    def test_blank_season_number_normalizes_to_none(self):
        """An empty season_number (non-season types) matches season_number IS NULL."""
        links = streaming_tags.manual_streaming_links(
            "238", Sources.TMDB.value, MediaTypes.MOVIE.value, ""
        )
        self.assertEqual(links.count(), 2)
