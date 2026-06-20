"""Tests for E2 genre/year extraction from provider metadata (offline)."""

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from app import metadata_fields
from app.models import MediaTypes, Sources

# The autouse conftest fixture stubs the module attribute ``fetch_for_item`` to
# keep the on-add signal offline. Capture the real function here (at import, before
# any fixture runs) so these tests can exercise it directly, patching only the
# network call it makes.
_real_fetch_for_item = metadata_fields.fetch_for_item

MOVIE_YEAR = 2008
TV_YEAR = 1994
ANIME_YEAR = 2009


class GenresFromTests(SimpleTestCase):
    """``genres_from`` normalizes the provider ``genres`` field to a list."""

    def test_returns_genre_list(self):
        """A provider genre list passes through unchanged."""
        self.assertEqual(
            metadata_fields.genres_from({"genres": ["Action", "Drama"]}),
            ["Action", "Drama"],
        )

    def test_none_becomes_empty_list(self):
        """Providers return None when the catalog has no genres."""
        self.assertEqual(metadata_fields.genres_from({"genres": None}), [])

    def test_missing_key_becomes_empty_list(self):
        """A metadata dict without a genres key yields an empty list."""
        self.assertEqual(metadata_fields.genres_from({}), [])


class YearFromTests(SimpleTestCase):
    """``year_from`` pulls the leading year from the item's own date."""

    def test_movie_release_date(self):
        """Movies use details.release_date."""
        self.assertEqual(
            metadata_fields.year_from({"details": {"release_date": "2008-05-07"}}),
            MOVIE_YEAR,
        )

    def test_tv_first_air_date(self):
        """TV uses details.first_air_date."""
        self.assertEqual(
            metadata_fields.year_from({"details": {"first_air_date": "1994-09-22"}}),
            TV_YEAR,
        )

    def test_anime_start_date(self):
        """Anime uses details.start_date."""
        self.assertEqual(
            metadata_fields.year_from({"details": {"start_date": "2009-04-03"}}),
            ANIME_YEAR,
        )

    def test_partial_dates(self):
        """MAL emits bare years / year-month for vague release dates."""
        self.assertEqual(
            metadata_fields.year_from({"details": {"start_date": "2009"}}),
            ANIME_YEAR,
        )
        self.assertEqual(
            metadata_fields.year_from({"details": {"start_date": "2009-04"}}),
            ANIME_YEAR,
        )

    def test_empty_or_missing_date_is_none(self):
        """Empty, None, or absent dates yield None."""
        self.assertIsNone(metadata_fields.year_from({"details": {"release_date": ""}}))
        self.assertIsNone(
            metadata_fields.year_from({"details": {"release_date": None}}),
        )
        self.assertIsNone(metadata_fields.year_from({"details": {}}))
        self.assertIsNone(metadata_fields.year_from({}))

    def test_first_present_date_key_wins(self):
        """release_date precedes start_date in priority order."""
        metadata = {"details": {"release_date": "2010-01-01", "start_date": "1999"}}
        self.assertEqual(metadata_fields.year_from(metadata), 2010)


class FetchForItemTests(SimpleTestCase):
    """``fetch_for_item`` calls the provider then extracts genre + year."""

    def _item(self, media_type=MediaTypes.MOVIE.value, season_number=None):
        return SimpleNamespace(
            media_type=media_type,
            media_id="550",
            source=Sources.TMDB.value,
            season_number=season_number,
        )

    def test_returns_genres_and_year(self):
        """Both genre and year are extracted when present."""
        metadata = {"genres": ["Drama"], "details": {"release_date": "1999-10-15"}}
        with patch(
            "app.metadata_fields.services.get_media_metadata",
            return_value=metadata,
        ):
            fields = _real_fetch_for_item(self._item())

        self.assertEqual(fields, {"genres": ["Drama"], "release_year": 1999})

    def test_year_only_still_returns(self):
        """A year with no genres still produces a row."""
        with patch(
            "app.metadata_fields.services.get_media_metadata",
            return_value={"genres": None, "details": {"release_date": "2001"}},
        ):
            fields = _real_fetch_for_item(self._item())

        self.assertEqual(fields, {"genres": [], "release_year": 2001})

    def test_genres_only_still_returns(self):
        """Genres with no year still produce a row."""
        with patch(
            "app.metadata_fields.services.get_media_metadata",
            return_value={"genres": ["Action"], "details": {}},
        ):
            fields = _real_fetch_for_item(self._item())

        self.assertEqual(fields, {"genres": ["Action"], "release_year": None})

    def test_no_data_returns_none(self):
        """Neither genre nor year means no row to write."""
        with patch(
            "app.metadata_fields.services.get_media_metadata",
            return_value={"genres": None, "details": {}},
        ):
            self.assertIsNone(_real_fetch_for_item(self._item()))

    def test_season_passes_season_number(self):
        """Season metadata requires the season number be passed through."""
        with patch(
            "app.metadata_fields.services.get_media_metadata",
            return_value={"genres": ["Comedy"], "details": {}},
        ) as mock_get:
            _real_fetch_for_item(
                self._item(media_type=MediaTypes.SEASON.value, season_number=2),
            )

        self.assertEqual(mock_get.call_args.args[3], [2])

    def test_non_season_passes_no_season_number(self):
        """Non-season items pass no season number."""
        with patch(
            "app.metadata_fields.services.get_media_metadata",
            return_value={"genres": ["Comedy"], "details": {}},
        ) as mock_get:
            _real_fetch_for_item(self._item())

        self.assertIsNone(mock_get.call_args.args[3])
