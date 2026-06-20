from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from app.forms import (
    AnimeForm,
    EpisodeForm,
    GameForm,
    ManualItemForm,
    SeasonForm,
    TvForm,
)
from app.models import (
    TV,
    AnimeAvailability,
    AvailabilitySource,
    Item,
    MediaTypes,
    Season,
    Sources,
    Status,
)


class BasicMediaForm(TestCase):
    """Test the standard media form."""

    def setUp(self):
        """Create a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Anime",
            image="http://example.com/image.jpg",
        )

        Item.objects.create(
            media_id="1",
            source=Sources.TMDB.value,
            media_type=MediaTypes.TV.value,
            title="Test tv",
            image="http://example.com/image.jpg",
        )

    def test_valid_media_form(self):
        """Test the standard media form with valid data."""
        form_data = {
            "media_id": "1",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "user": self.user.id,
            "score": 7.5,
            "progress": 25,
            "status": Status.PAUSED.value,
            "repeats": 0,
            "start_date": "2023-02-01",
            "end_date": "2023-06-30",
            "notes": "New notes",
        }
        form = AnimeForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_valid_tv_form(self):
        """Test the TV form with valid data."""
        form_data = {
            "media_id": "1",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.TV.value,
            "user": self.user.id,
            "score": 7.5,
            "status": Status.COMPLETED.value,
            "repeats": 0,
            "notes": "New notes",
        }
        form = TvForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_media_date_fields_are_optional(self):
        """Start and end dates should remain optional in tracking forms."""
        form = AnimeForm()

        self.assertFalse(form.fields["start_date"].required)
        self.assertFalse(form.fields["end_date"].required)

    def test_valid_season_form(self):
        """Test the season form with valid data."""
        form_data = {
            "media_id": "1",
            "source": Sources.TMDB.value,
            "media_type": MediaTypes.SEASON.value,
            "user": self.user.id,
            "score": 7.5,
            "status": Status.COMPLETED.value,
            "repeats": 0,
            "season_number": 1,
            "notes": "New notes",
        }
        form = SeasonForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_valid_episode_form(self):
        """Test the episode form with valid data."""
        form_data = {
            "end_date": "2023-06-01",
        }
        form = EpisodeForm(data=form_data)
        self.assertTrue(form.is_valid())

    def test_valid_episode_datetime_form(self):
        """Test the episode form with valid data."""
        form_data = {
            "end_date": "2023-06-01T12:00:00Z",
        }
        form = EpisodeForm(data=form_data)
        self.assertTrue(form.is_valid())


class BasicGameForm(TestCase):
    """Test the game form."""

    def setUp(self):
        """Create a user."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.IGDB.value,
            media_type=MediaTypes.GAME.value,
            title="Test Game",
            image="http://example.com/image.jpg",
        )

    def test_default_progress(self):
        """Test the game form using the default progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "25:00",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 1500)

    def test_plain_number_progress(self):
        """Test the game form with a plain number for hours (e.g., '5')."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "5",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 300)

    def test_alternate_progress(self):
        """Test the game form using an alternate progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "25h 00min",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 1500)

    def test_second_alternate_progress(self):
        """Test the game form using a second alternate progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "30min",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 30)

    def test_third_alternate_progress(self):
        """Test the game form using a second alternate progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "9h",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 540)

    def test_fourth_alternate_progress(self):
        """Test the game form using a second alternate progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "9h30min",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 570)

    def test_float_progress(self):
        """Test the game form with float progress format (e.g., 1.5 hours)."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "1.5",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 90)

    def test_float_progress_half_hour(self):
        """Test the game form with 0.5 float progress (30 minutes)."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "0.5",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertTrue(form.is_valid())
        self.assertEqual(form.cleaned_data["progress"], 30)

    def test_invalid_negative_float_progress(self):
        """Test that negative float progress is rejected."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "-1.5",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_invalid_inf_progress(self):
        """Test that infinity progress is rejected."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "inf",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_invalid_nan_progress(self):
        """Test that NaN progress is rejected."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "nan",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_invalid_progress(self):
        """Test the game form using an invalid default progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "25:00m",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())

    def test_invalid_minutes(self):
        """Test the game form using an invalid default progress format."""
        form_data = {
            "media_id": "1",
            "source": Sources.IGDB.value,
            "media_type": MediaTypes.GAME.value,
            "user": self.user.id,
            "status": Status.COMPLETED.value,
            "progress": "25h61m",
            "repeats": 0,
        }
        form = GameForm(data=form_data)
        self.assertFalse(form.is_valid())


class ManualItemFormTest(TestCase):
    """Test the manual item form functionality."""

    def setUp(self):
        """Create a user and necessary parent items."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)

        # Create a manual TV show
        self.tv_item = Item.objects.create(
            media_id="manual_tv_1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.TV.value,
            title="Test Manual TV",
            image="http://example.com/tv.jpg",
        )
        self.tv = TV.objects.create(
            item=self.tv_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

        # Create a manual Season
        self.season_item = Item.objects.create(
            media_id="manual_tv_1",
            source=Sources.MANUAL.value,
            media_type=MediaTypes.SEASON.value,
            title="Test Manual TV",
            season_number=1,
            image="http://example.com/season.jpg",
        )
        self.season = Season.objects.create(
            item=self.season_item,
            user=self.user,
            status=Status.IN_PROGRESS.value,
        )

    def test_init_with_user(self):
        """Test form initialization with user parameter."""
        form = ManualItemForm(user=self.user)
        self.assertEqual(form.fields["parent_tv"].queryset.count(), 1)
        self.assertEqual(form.fields["parent_season"].queryset.count(), 1)

    def test_init_without_user(self):
        """Test form initialization without user parameter."""
        form = ManualItemForm()
        self.assertEqual(form.fields["parent_tv"].queryset.count(), 0)
        self.assertEqual(form.fields["parent_season"].queryset.count(), 0)

    def test_valid_standalone_media(self):
        """Test creating a standalone media item (movie, anime, etc.)."""
        form_data = {
            "media_type": MediaTypes.MOVIE.value,
            "title": "Test Manual Movie",
            "image": "http://example.com/movie.jpg",
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid())

        # Save and verify
        item = form.save()
        self.assertEqual(item.source, Sources.MANUAL.value)
        self.assertTrue(item.media_id)
        self.assertIsNone(item.season_number)
        self.assertIsNone(item.episode_number)

    def test_valid_season_creation(self):
        """Test creating a season for an existing TV show."""
        form_data = {
            "media_type": MediaTypes.SEASON.value,
            "parent_tv": self.tv.id,
            "season_number": 2,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid())

        # Save and verify
        item = form.save()
        self.assertEqual(item.source, Sources.MANUAL.value)
        self.assertEqual(item.media_id, self.tv_item.media_id)
        self.assertEqual(item.title, self.tv_item.title)
        self.assertEqual(item.season_number, 2)
        self.assertIsNone(item.episode_number)

    def test_valid_episode_creation(self):
        """Test creating an episode for an existing season."""
        form_data = {
            "media_type": MediaTypes.EPISODE.value,
            "parent_season": self.season.id,
            "episode_number": 5,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid())

        # Save and verify
        item = form.save()
        self.assertEqual(item.source, Sources.MANUAL.value)
        self.assertEqual(item.media_id, self.season_item.media_id)
        self.assertEqual(item.title, self.season_item.title)
        self.assertEqual(item.season_number, self.season_item.season_number)
        self.assertEqual(item.episode_number, 5)

    def test_missing_title_for_standalone(self):
        """Test that title is required for standalone."""
        form_data = {
            "media_type": MediaTypes.MOVIE.value,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertFalse(form.is_valid())
        self.assertIn("title", form.errors)

    def test_missing_parent_for_season(self):
        """Test that parent TV is required for seasons."""
        form_data = {
            "media_type": MediaTypes.SEASON.value,
            "season_number": 3,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertFalse(form.is_valid())

    def test_missing_parent_for_episode(self):
        """Test that parent season is required for episodes."""
        form_data = {
            "media_type": MediaTypes.EPISODE.value,
            "episode_number": 2,
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertFalse(form.is_valid())

    def test_default_image(self):
        """Test that default image is used when none provided."""
        form_data = {
            "media_type": MediaTypes.BOOK.value,
            "title": "Test Manual Book",
        }
        form = ManualItemForm(data=form_data, user=self.user)
        self.assertTrue(form.is_valid())

        # Save and verify
        item = form.save()
        self.assertEqual(item.image, settings.IMG_NONE)

    def test_manual_id_generation(self):
        """Test that unique manual IDs are generated."""
        # Create first item
        form1 = ManualItemForm(
            data={"media_type": MediaTypes.ANIME.value, "title": "Test Anime 1"},
            user=self.user,
        )
        self.assertTrue(form1.is_valid())
        item1 = form1.save()

        # Create second item
        form2 = ManualItemForm(
            data={"media_type": MediaTypes.ANIME.value, "title": "Test Anime 2"},
            user=self.user,
        )
        self.assertTrue(form2.is_valid())
        item2 = form2.save()

        # IDs should be different
        self.assertNotEqual(item1.media_id, item2.media_id)
        self.assertTrue(item1.media_id)


class AnimeFormAvailabilityTests(TestCase):
    """Test AnimeForm's availability save-override (change-detection)."""

    def setUp(self):
        """Create a user and an anime Item to attach availability rows to."""
        self.credentials = {"username": "test", "password": "12345"}
        self.user = get_user_model().objects.create_user(**self.credentials)
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Anime",
            image="http://example.com/image.jpg",
        )

    def _base_form_data(self, audio="", subtitle=""):
        return {
            "media_id": "1",
            "source": Sources.MAL.value,
            "media_type": MediaTypes.ANIME.value,
            "user": self.user.id,
            "score": 7.5,
            "progress": 5,
            "status": Status.IN_PROGRESS.value,
            "repeats": 0,
            "audio_locales": audio,
            "subtitle_locales": subtitle,
        }

    def _save_form(self, form):
        """Save a validated AnimeForm bound to self.item, mirroring the view.

        Mirrors create_entry's pattern (views.py): the instance's ``item``
        (and ``user``) are set directly on the unsaved instance before the
        single ``save()`` call — not via commit=False + a second save.
        """
        form.instance.item = self.item
        form.instance.user = self.user
        return form.save()

    def test_empty_submit_with_no_existing_row_creates_nothing(self):
        """Submitting blank locale fields with no prior row is a no-op."""
        form = AnimeForm(data=self._base_form_data())
        self.assertTrue(form.is_valid(), form.errors)
        self._save_form(form)

        self.assertFalse(
            AnimeAvailability.objects.filter(item_id=self.item.id).exists(),
        )

    def test_non_empty_submit_with_no_existing_row_creates_manual_row(self):
        """A first-time non-empty submit creates a manual-source row."""
        form = AnimeForm(
            data=self._base_form_data(audio="Japanese, English", subtitle="English"),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self._save_form(form)

        availability = AnimeAvailability.objects.get(item_id=self.item.id)
        self.assertEqual(availability.audio_locales, ["ja-JP", "en-US"])
        self.assertEqual(availability.subtitle_locales, ["en-US"])
        self.assertEqual(availability.source, AvailabilitySource.MANUAL.value)

    def test_unchanged_resubmit_does_not_touch_existing_row(self):
        """Resubmitting identical values is a no-op (last-write-wins guard).

        A routine score/status save round-trips the prefilled values
        unchanged; it must not flip a synced row's source back to manual or
        bump updated_at.
        """
        existing = AnimeAvailability.objects.create(
            item=self.item,
            audio_locales=["ja-JP"],
            subtitle_locales=[],
            source=AvailabilitySource.MYDUBLIST.value,
        )
        original_updated_at = existing.updated_at

        form = AnimeForm(
            data=self._base_form_data(audio="Japanese", subtitle=""),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self._save_form(form)

        existing.refresh_from_db()
        self.assertEqual(existing.source, AvailabilitySource.MYDUBLIST.value)
        self.assertEqual(existing.updated_at, original_updated_at)

    def test_changed_resubmit_updates_row_and_marks_manual(self):
        """A genuine change upserts the row and flips source to manual."""
        AnimeAvailability.objects.create(
            item=self.item,
            audio_locales=["ja-JP"],
            subtitle_locales=[],
            source=AvailabilitySource.MYDUBLIST.value,
        )

        form = AnimeForm(
            data=self._base_form_data(audio="Japanese, English", subtitle=""),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self._save_form(form)

        availability = AnimeAvailability.objects.get(item_id=self.item.id)
        self.assertEqual(availability.audio_locales, ["ja-JP", "en-US"])
        self.assertEqual(availability.source, AvailabilitySource.MANUAL.value)

    def test_unknown_language_token_raises_validation_error(self):
        """A token that isn't a known display name or code-shaped fails clean."""
        form = AnimeForm(data=self._base_form_data(audio="Klingon"))
        self.assertFalse(form.is_valid())
        self.assertIn("audio_locales", form.errors)

    def test_unmapped_code_shaped_token_passes_through(self):
        """A code-shaped but unmapped token (e.g. from a sync) is accepted raw."""
        form = AnimeForm(data=self._base_form_data(audio="xx-XX"))
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["audio_locales"], ["xx-XX"])

    def test_duplicate_tokens_collapsed_preserving_order(self):
        """Duplicate languages in the input collapse to one, order preserved."""
        form = AnimeForm(
            data=self._base_form_data(audio="Japanese, English, Japanese"),
        )
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["audio_locales"], ["ja-JP", "en-US"])

    def test_clearing_existing_row_empties_and_marks_manual(self):
        """Blanking the fields on a populated row empties it and marks it manual."""
        AnimeAvailability.objects.create(
            item=self.item,
            audio_locales=["ja-JP"],
            subtitle_locales=["en-US"],
            source=AvailabilitySource.MYDUBLIST.value,
        )

        form = AnimeForm(data=self._base_form_data(audio="", subtitle=""))
        self.assertTrue(form.is_valid(), form.errors)
        self._save_form(form)

        availability = AnimeAvailability.objects.get(item_id=self.item.id)
        self.assertEqual(availability.audio_locales, [])
        self.assertEqual(availability.subtitle_locales, [])
        self.assertEqual(availability.source, AvailabilitySource.MANUAL.value)
