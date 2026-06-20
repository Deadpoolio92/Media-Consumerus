from datetime import timedelta
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase, override_settings
from django.utils import timezone

from app.models import (
    Anime,
    AnimeAvailability,
    AvailabilitySource,
    Item,
    MediaTypes,
    Sources,
    Status,
    UserMessage,
    UserMessageLevel,
)
from app.tasks import (
    apply_mydublist_locales,
    cleanup_user_messages,
    fetch_one_availability,
    sync_dub_availability,
)


class CleanupUserMessagesTaskTests(TestCase):
    """Test cleanup of old shown user messages."""

    def setUp(self):
        """Create a user for task tests."""
        self.user = get_user_model().objects.create_user(
            username="test",
        )

    @override_settings(USER_MESSAGE_RETENTION_DAYS=30)
    def test_cleanup_user_messages_deletes_only_old_shown_messages(self):
        """Delete only shown messages older than the retention window."""
        now = timezone.now()
        old_shown = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="old shown",
            shown_at=now - timedelta(days=31),
        )
        recent_shown = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="recent shown",
            shown_at=now - timedelta(days=5),
        )
        unseen = UserMessage.objects.create(
            user=self.user,
            level=UserMessageLevel.INFO,
            message="unseen",
        )

        deleted_count = cleanup_user_messages()

        self.assertEqual(deleted_count, 1)
        self.assertFalse(UserMessage.objects.filter(id=old_shown.id).exists())
        self.assertTrue(UserMessage.objects.filter(id=recent_shown.id).exists())
        self.assertTrue(UserMessage.objects.filter(id=unseen.id).exists())


class SyncDubAvailabilityTaskTests(TestCase):
    """Test the daily MyDubList dub-availability sync (library-bounded)."""

    def setUp(self):
        """Create a covered MAL anime plus out-of-scope items."""
        self.anime = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Covered Anime",
            image="http://example.com/1.jpg",
        )
        # Out of scope: manual-source anime (UUID id) and a TMDB movie.
        self.manual_anime = Item.objects.create(
            media_id="manual-uuid",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Manual Anime",
            image="http://example.com/m.jpg",
        )
        self.movie = Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.MOVIE.value,
            title="A Movie",
            image="http://example.com/mv.jpg",
        )

    def _patch_dataset(self, dataset):
        """Patch the network fetch to return a canned dataset."""
        return patch(
            "app.tasks.mydublist.fetch_dataset",
            return_value=dataset,
        )

    def test_covered_title_upserts_audio_and_source(self):
        """A covered anime gets audio_locales + source=mydublist; scope is respected."""
        with self._patch_dataset({"1": ["ja-JP", "en-US"]}):
            updated = sync_dub_availability()

        self.assertEqual(updated, 1)
        availability = AnimeAvailability.objects.get(item=self.anime)
        self.assertEqual(availability.audio_locales, ["ja-JP", "en-US"])
        self.assertEqual(availability.source, AvailabilitySource.MYDUBLIST.value)
        # Out-of-scope items never get a row.
        self.assertFalse(
            AnimeAvailability.objects.filter(item=self.manual_anime).exists(),
        )
        self.assertFalse(AnimeAvailability.objects.filter(item=self.movie).exists())

    def test_uncovered_title_is_never_blanked(self):
        """CRITICAL: a title MyDubList has no data for keeps its prior audio."""
        AnimeAvailability.objects.create(
            item=self.anime,
            audio_locales=["ja-JP"],
            source=AvailabilitySource.MANUAL.value,
        )
        with self._patch_dataset({}):  # dataset misses media_id "1"
            updated = sync_dub_availability()

        self.assertEqual(updated, 0)
        availability = AnimeAvailability.objects.get(item=self.anime)
        self.assertEqual(availability.audio_locales, ["ja-JP"])
        self.assertEqual(availability.source, AvailabilitySource.MANUAL.value)

    def test_subtitle_locales_never_touched_by_sync(self):
        """CRITICAL: a manual subtitle list survives an audio sync."""
        AnimeAvailability.objects.create(
            item=self.anime,
            audio_locales=["ja-JP"],
            subtitle_locales=["en-US", "es-419"],
            source=AvailabilitySource.MANUAL.value,
        )
        with self._patch_dataset({"1": ["ja-JP", "en-US"]}):
            sync_dub_availability()

        availability = AnimeAvailability.objects.get(item=self.anime)
        self.assertEqual(availability.audio_locales, ["ja-JP", "en-US"])
        self.assertEqual(availability.subtitle_locales, ["en-US", "es-419"])

    def test_last_write_wins_overwrites_manual_audio(self):
        """A differing manual audio list IS overwritten (documents chosen behavior)."""
        AnimeAvailability.objects.create(
            item=self.anime,
            audio_locales=["fr-FR"],
            source=AvailabilitySource.MANUAL.value,
        )
        with self._patch_dataset({"1": ["ja-JP", "en-US"]}):
            updated = sync_dub_availability()

        self.assertEqual(updated, 1)
        availability = AnimeAvailability.objects.get(item=self.anime)
        self.assertEqual(availability.audio_locales, ["ja-JP", "en-US"])
        self.assertEqual(availability.source, AvailabilitySource.MYDUBLIST.value)

    def test_equal_data_is_a_noop(self):
        """Unchanged audio doesn't bump updated_at or re-flip source (idempotent)."""
        AnimeAvailability.objects.create(
            item=self.anime,
            audio_locales=["ja-JP", "en-US"],
            source=AvailabilitySource.MYDUBLIST.value,
        )
        old = timezone.now() - timedelta(days=2)
        # .update() bypasses auto_now so we can detect a later save.
        AnimeAvailability.objects.filter(item=self.anime).update(updated_at=old)

        with self._patch_dataset({"1": ["ja-JP", "en-US"]}):
            updated = sync_dub_availability()

        self.assertEqual(updated, 0)
        availability = AnimeAvailability.objects.get(item=self.anime)
        self.assertEqual(availability.updated_at, old)
        self.assertEqual(availability.source, AvailabilitySource.MYDUBLIST.value)

    def test_manual_entry_with_matching_data_keeps_manual_source(self):
        """A manual row whose audio already matches MyDubList stays source=manual."""
        AnimeAvailability.objects.create(
            item=self.anime,
            audio_locales=["ja-JP", "en-US"],
            source=AvailabilitySource.MANUAL.value,
        )
        with self._patch_dataset({"1": ["ja-JP", "en-US"]}):
            updated = sync_dub_availability()

        self.assertEqual(updated, 0)
        availability = AnimeAvailability.objects.get(item=self.anime)
        self.assertEqual(availability.source, AvailabilitySource.MANUAL.value)

    def test_create_race_falls_back_to_update(self):
        """CRITICAL: a concurrent create (on-add fetch vs. daily sync) doesn't raise.

        Simulates the TOCTOU window in apply_mydublist_locales: the existence
        check sees no row, but another worker inserts one before our create()
        runs. The IntegrityError must be caught and the write retried as an
        update against the now-existing row instead of propagating.
        """
        # The "other worker" wins the race and creates the row first.
        AnimeAvailability.objects.create(
            item=self.anime,
            audio_locales=["fr-FR"],
            source=AvailabilitySource.MANUAL.value,
        )
        with patch(
            "app.tasks.AnimeAvailability.objects.create",
            side_effect=IntegrityError,
        ):
            updated = apply_mydublist_locales(self.anime, ["ja-JP", "en-US"])

        self.assertTrue(updated)
        availability = AnimeAvailability.objects.get(item=self.anime)
        self.assertEqual(availability.audio_locales, ["ja-JP", "en-US"])
        self.assertEqual(availability.source, AvailabilitySource.MYDUBLIST.value)

    def test_fetch_failure_aborts_without_blanking(self):
        """A dataset-fetch failure returns 0 and leaves existing data intact."""
        AnimeAvailability.objects.create(
            item=self.anime,
            audio_locales=["ja-JP"],
            source=AvailabilitySource.MANUAL.value,
        )
        with patch(
            "app.tasks.mydublist.fetch_dataset",
            side_effect=requests.exceptions.ConnectionError,
        ):
            updated = sync_dub_availability()

        self.assertEqual(updated, 0)
        availability = AnimeAvailability.objects.get(item=self.anime)
        self.assertEqual(availability.audio_locales, ["ja-JP"])
        self.assertEqual(availability.source, AvailabilitySource.MANUAL.value)


class FetchOneAvailabilityTaskTests(TestCase):
    """Test the on-add best-effort single-title availability fetch."""

    def setUp(self):
        """Create the anime Item the fetch targets."""
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Covered Anime",
            image="http://example.com/1.jpg",
        )

    def test_covered_title_writes_row(self):
        """A covered title gets a row with source=mydublist."""
        with patch(
            "app.tasks.mydublist.get_locales",
            return_value=["ja-JP", "en-US"],
        ):
            wrote = fetch_one_availability(self.item.id)

        self.assertTrue(wrote)
        availability = AnimeAvailability.objects.get(item=self.item)
        self.assertEqual(availability.audio_locales, ["ja-JP", "en-US"])
        self.assertEqual(availability.source, AvailabilitySource.MYDUBLIST.value)

    def test_uncovered_title_writes_nothing(self):
        """A miss (None) writes no row (never blank)."""
        with patch("app.tasks.mydublist.get_locales", return_value=None):
            wrote = fetch_one_availability(self.item.id)

        self.assertFalse(wrote)
        self.assertFalse(AnimeAvailability.objects.filter(item=self.item).exists())

    def test_missing_item_is_safe(self):
        """A deleted item id returns False without fetching."""
        with patch("app.tasks.mydublist.get_locales") as mock_get:
            wrote = fetch_one_availability(999999)

        self.assertFalse(wrote)
        mock_get.assert_not_called()

    def test_fetch_error_is_swallowed(self):
        """A network failure is logged + swallowed (returns False, no raise)."""
        with patch(
            "app.tasks.mydublist.get_locales",
            side_effect=requests.exceptions.ConnectionError,
        ):
            wrote = fetch_one_availability(self.item.id)

        self.assertFalse(wrote)
        self.assertFalse(AnimeAvailability.objects.filter(item=self.item).exists())


class AnimeOnAddSignalTests(TestCase):
    """Test post_save(Anime) -> availability fetch enqueue (eager in tests)."""

    def setUp(self):
        """Create a user and a covered MAL anime Item."""
        self.user = get_user_model().objects.create_user(username="test")
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Covered Anime",
            image="http://example.com/1.jpg",
        )

    def test_new_anime_populates_availability(self):
        """Tracking a new anime fills its availability via the signal."""
        with patch(
            "app.tasks.mydublist.get_locales",
            return_value=["ja-JP", "en-US"],
        ):
            Anime.objects.create(
                item=self.item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        availability = AnimeAvailability.objects.get(item=self.item)
        self.assertEqual(availability.audio_locales, ["ja-JP", "en-US"])
        self.assertEqual(availability.source, AvailabilitySource.MYDUBLIST.value)

    def test_add_succeeds_when_fetch_fails(self):
        """CRITICAL: a MyDubList failure must NOT block tracking the anime."""
        with patch(
            "app.tasks.mydublist.get_locales",
            side_effect=requests.exceptions.ConnectionError,
        ):
            anime = Anime.objects.create(
                item=self.item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        self.assertTrue(Anime.objects.filter(pk=anime.pk).exists())
        self.assertFalse(AnimeAvailability.objects.filter(item=self.item).exists())

    def test_broker_failure_on_enqueue_does_not_block_track_anime(self):
        """CRITICAL: if .delay() itself raises (broker down), tracking still succeeds."""
        with patch(
            "app.tasks.fetch_one_availability.delay",
            side_effect=Exception("broker down"),
        ):
            anime = Anime.objects.create(
                item=self.item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        self.assertTrue(Anime.objects.filter(pk=anime.pk).exists())
        self.assertFalse(AnimeAvailability.objects.filter(item=self.item).exists())

    def test_edit_does_not_refetch(self):
        """Only a NEW anime triggers a fetch; later edits don't re-enqueue."""
        with patch("app.tasks.mydublist.get_locales", return_value=["ja-JP"]):
            anime = Anime.objects.create(
                item=self.item,
                user=self.user,
                status=Status.PLANNING.value,
            )

        with patch("app.tasks.mydublist.get_locales") as mock_get:
            anime.notes = "edited"
            anime.save()

        mock_get.assert_not_called()
