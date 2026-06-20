"""Tests for E2 list filters (rating / year / genre / language) in MediaManager."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models import QuerySet
from django.test import TestCase

from app.models import (
    Anime,
    AnimeAvailability,
    BasicMedia,
    Item,
    ItemMetadata,
    MediaTypes,
    Movie,
    Sources,
    Status,
)
from users.models import MediaStatusChoices


class MediaManagerFilterTests(TestCase):
    """Test get_media_list's rating/year/genre/language filters + filter choices."""

    def setUp(self):
        """Create a small movie + anime library with denormalized metadata."""
        self.user = get_user_model().objects.create_user(username="test")
        for media_type in MediaTypes.values:
            setattr(self.user, f"{media_type.lower()}_enabled", True)
        self.user.save()

        # Mock provider metadata so save()/calendar reload stay offline.
        patcher = patch("app.providers.services.get_media_metadata")
        mock_metadata = patcher.start()
        self.addCleanup(patcher.stop)
        mock_metadata.return_value = {"max_progress": 1}

        # --- Movies: rating / year / genre coverage ---
        self.movies = {}
        movie_specs = [
            ("550", "Fight Club", 9, 1999, ["Drama", "Thriller"]),
            ("603", "The Matrix", 8, 1999, ["Sci-Fi", "Action"]),
            ("27205", "Inception", 10, 2010, ["Sci-Fi", "Action", "Thriller"]),
            ("99999", "Unrated Pick", None, 2020, ["Comedy"]),
        ]
        for media_id, title, score, year, genres in movie_specs:
            item = Item.objects.create(
                media_id=media_id,
                source=Sources.TMDB.value,
                media_type=MediaTypes.MOVIE.value,
                title=title,
                image=f"http://example.com/{media_id}.jpg",
            )
            self.movies[title] = Movie.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                score=score,
            )
            ItemMetadata.objects.create(
                item=item,
                genres=genres,
                release_year=year,
            )

        # A movie with no denormalized metadata yet (must be excluded from
        # genre/year filters, never crash).
        self.no_meta_item = Item.objects.create(
            media_id="11",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="No Metadata",
            image="http://example.com/11.jpg",
        )
        self.no_meta_movie = Movie.objects.create(
            item=self.no_meta_item,
            user=self.user,
            status=Status.COMPLETED.value,
            score=9,
        )

        # --- Anime: language coverage ---
        self.anime = {}
        anime_specs = [
            ("1", "Cowboy Bebop", 9, 1998, ["Action"], ["ja-JP", "en-US"], []),
            ("20", "Naruto", 7, 2002, ["Adventure"], ["ja-JP"], ["es-419"]),
        ]
        for media_id, title, score, year, genres, audio, subs in anime_specs:
            item = Item.objects.create(
                media_id=media_id,
                source=Sources.MAL.value,
                media_type=MediaTypes.ANIME.value,
                title=title,
                image=f"http://example.com/anime{media_id}.jpg",
            )
            self.anime[title] = Anime.objects.create(
                item=item,
                user=self.user,
                status=Status.COMPLETED.value,
                score=score,
            )
            ItemMetadata.objects.create(item=item, genres=genres, release_year=year)
            AnimeAvailability.objects.create(
                item=item,
                audio_locales=audio,
                subtitle_locales=subs,
            )

    def _movie_titles(self, filters):
        result = BasicMedia.objects.get_media_list(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            status_filter=MediaStatusChoices.ALL,
            sort_filter="score",
            filters=filters,
        )
        return {media.item.title for media in result}

    def _anime_titles(self, filters):
        result = BasicMedia.objects.get_media_list(
            user=self.user,
            media_type=MediaTypes.ANIME.value,
            status_filter=MediaStatusChoices.ALL,
            sort_filter="score",
            filters=filters,
        )
        return {media.item.title for media in result}

    def test_rating_minimum_filter(self):
        """rating='9' keeps score >= 9 (the displayed row)."""
        self.assertEqual(
            self._movie_titles({"rating": "9"}),
            {"Fight Club", "Inception", "No Metadata"},
        )

    def test_rating_exact_ten(self):
        """rating='10' keeps only a perfect score."""
        self.assertEqual(self._movie_titles({"rating": "10"}), {"Inception"})

    def test_rating_unrated_filter(self):
        """rating='unrated' keeps only score IS NULL."""
        self.assertEqual(self._movie_titles({"rating": "unrated"}), {"Unrated Pick"})

    def test_rating_all_is_noop(self):
        """An unparseable rating (e.g. 'all') filters nothing."""
        self.assertEqual(len(self._movie_titles({"rating": "all"})), 5)

    def test_year_filter(self):
        """Year filters on the denormalized release_year."""
        self.assertEqual(
            self._movie_titles({"year": "1999"}),
            {"Fight Club", "The Matrix"},
        )

    def test_year_filter_excludes_items_without_metadata(self):
        """An item with no ItemMetadata never matches a year filter."""
        self.assertNotIn("No Metadata", self._movie_titles({"year": "2020"}))

    def test_genre_filter(self):
        """Genre keeps items whose denormalized genres contain the value."""
        self.assertEqual(
            self._movie_titles({"genre": "Sci-Fi"}),
            {"The Matrix", "Inception"},
        )

    def test_genre_filter_returns_list(self):
        """A JSON (Python-side) filter materializes to a list, not a queryset."""
        result = BasicMedia.objects.get_media_list(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            status_filter=MediaStatusChoices.ALL,
            sort_filter="score",
            filters={"genre": "Thriller"},
        )
        self.assertIsInstance(result, list)
        self.assertEqual(
            {media.item.title for media in result},
            {"Fight Club", "Inception"},
        )

    def test_genre_filter_excludes_items_without_metadata(self):
        """An item with no ItemMetadata is silently excluded (no crash)."""
        self.assertNotIn("No Metadata", self._movie_titles({"genre": "Drama"}))

    def test_combined_rating_and_genre(self):
        """SQL (rating) + Python (genre) filters compose."""
        self.assertEqual(
            self._movie_titles({"rating": "10", "genre": "Thriller"}),
            {"Inception"},
        )

    def test_language_filter_audio(self):
        """Language matches anime with the code in audio_locales."""
        self.assertEqual(self._anime_titles({"language": "en-US"}), {"Cowboy Bebop"})

    def test_language_filter_subtitle(self):
        """Language also matches a code present only in subtitle_locales."""
        self.assertEqual(self._anime_titles({"language": "es-419"}), {"Naruto"})

    def test_language_filter_shared_code(self):
        """A code in both anime matches both."""
        self.assertEqual(
            self._anime_titles({"language": "ja-JP"}),
            {"Cowboy Bebop", "Naruto"},
        )

    def test_no_filters_returns_queryset(self):
        """With no filters the result stays a lazy queryset (home/sort callers)."""
        result = BasicMedia.objects.get_media_list(
            user=self.user,
            media_type=MediaTypes.MOVIE.value,
            status_filter=MediaStatusChoices.ALL,
            sort_filter="score",
            filters={},
        )
        self.assertIsInstance(result, QuerySet)

    def test_get_filter_options_movie(self):
        """Genres are sorted; years are distinct + descending; no languages."""
        options = BasicMedia.objects.get_filter_options(
            self.user,
            MediaTypes.MOVIE.value,
        )
        self.assertEqual(
            options["genres"],
            ["Action", "Comedy", "Drama", "Sci-Fi", "Thriller"],
        )
        self.assertEqual(options["years"], [2020, 2010, 1999])
        self.assertEqual(options["languages"], [])

    def test_get_filter_options_anime_languages_ordered(self):
        """Anime languages follow the canonical LOCALE_DISPLAY order with labels."""
        options = BasicMedia.objects.get_filter_options(
            self.user,
            MediaTypes.ANIME.value,
        )
        self.assertEqual(
            options["languages"],
            [
                ("ja-JP", "Japanese"),
                ("en-US", "English"),
                ("es-419", "Spanish (Latin America)"),
            ],
        )
