from django.test import TestCase

from app.models import AnimeAvailability, AvailabilitySource, Item, MediaTypes, Sources


class AnimeAvailabilityModel(TestCase):
    """Test case for the AnimeAvailability model."""

    def setUp(self):
        """Create the anime Item this availability row hangs off of."""
        self.item = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Test Anime",
            image="http://example.com/image.jpg",
        )

    def test_defaults_are_empty_lists_and_manual_source(self):
        """A row created without explicit locales/source gets sane defaults."""
        availability = AnimeAvailability.objects.create(item=self.item)

        self.assertEqual(availability.audio_locales, [])
        self.assertEqual(availability.subtitle_locales, [])
        self.assertEqual(availability.source, AvailabilitySource.MANUAL.value)
        self.assertIsNotNone(availability.updated_at)

    def test_str_representation_is_item_title(self):
        """__str__ delegates to the related Item's title."""
        availability = AnimeAvailability.objects.create(item=self.item)
        self.assertEqual(str(availability), "Test Anime")

    def test_one_to_one_enforces_single_row_per_item(self):
        """An Item can only have one AnimeAvailability row."""
        AnimeAvailability.objects.create(item=self.item)
        with self.assertRaises(Exception):  # noqa: B017 - IntegrityError, backend-dependent
            AnimeAvailability.objects.create(item=self.item)

    def test_cascade_delete_when_item_removed(self):
        """Deleting the Item cascades to its AnimeAvailability row."""
        AnimeAvailability.objects.create(item=self.item)
        self.item.delete()
        self.assertFalse(AnimeAvailability.objects.exists())


class AnimeAvailabilityQueryabilityTests(TestCase):
    """E2-readiness: stored locale codes are queryable for the language filter."""

    def test_audio_locales_round_trip_as_list_and_filterable(self):
        """Codes persist as a real list and are matchable (SQLite-safe).

        E2's real filter is
        ``filter(item__availability__audio_locales__contains=["en-US"])`` on
        Postgres, but JSONField ``__contains`` is unsupported on the SQLite test
        DB (see planning/TODOS.md). This asserts the storage guarantee E1 makes:
        codes survive a DB round-trip as a list and can be matched.
        """
        dubbed = Item.objects.create(
            media_id="1",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Dubbed",
            image="http://example.com/1.jpg",
        )
        subbed_only = Item.objects.create(
            media_id="2",
            source=Sources.MAL.value,
            media_type=MediaTypes.ANIME.value,
            title="Sub only",
            image="http://example.com/2.jpg",
        )
        AnimeAvailability.objects.create(item=dubbed, audio_locales=["ja-JP", "en-US"])
        AnimeAvailability.objects.create(item=subbed_only, audio_locales=["ja-JP"])

        stored = AnimeAvailability.objects.get(item=dubbed)
        self.assertEqual(stored.audio_locales, ["ja-JP", "en-US"])  # a list, not str

        english_dubs = [
            row.item_id
            for row in AnimeAvailability.objects.all()
            if "en-US" in row.audio_locales
        ]
        self.assertEqual(english_dubs, [dubbed.id])
