"""Tests for the C1 dub/sub backfill (E9a). CR network + seed map are mocked."""

from unittest.mock import patch

from django.test import TestCase

from app.models import (
    AnimeAvailability,
    AvailabilitySource,
    Item,
    MediaTypes,
    Sources,
)
from integrations.crunchyroll import sync


def _anime(media_id, title):
    return Item.objects.create(
        media_id=media_id,
        source=Sources.MAL.value,
        media_type=MediaTypes.ANIME.value,
        title=title,
        image=f"http://example.com/{media_id}.jpg",
    )


def _entry(code, title, audio, subtitle):
    return {
        "code": code,
        "title": title,
        "type": "series",
        "audio_locales": audio,
        "subtitle_locales": subtitle,
    }


class BackfillC1Tests(TestCase):
    """backfill_c1 matching routes + write rules."""

    def _run(self, *, catalog, mal_to_cr, series=None):
        """Run backfill_c1 with the CR client + seed map mocked."""
        with (
            patch.object(sync.client, "fetch_catalog", return_value=catalog),
            patch.object(sync.client, "series", return_value=series),
            patch.object(sync.resolve, "mal_to_cr", return_value=mal_to_cr),
        ):
            return sync.backfill_c1("tok")

    def test_seed_code_hit(self):
        """Item whose MAL id is in the seed matches the catalog by CR code."""
        item = _anime("100", "Show A")
        counts = self._run(
            catalog=[_entry("GT100", "Show A", ["ja-JP", "en-US"], ["en-US"])],
            mal_to_cr={"100": "GT100"},
        )

        self.assertEqual((counts["written"], counts["via_seed"]), (1, 1))
        avail = AnimeAvailability.objects.get(item=item)
        self.assertEqual(avail.audio_locales, ["ja-JP", "en-US"])
        self.assertEqual(avail.subtitle_locales, ["en-US"])
        self.assertEqual(avail.source, AvailabilitySource.CRUNCHYROLL.value)

    def test_exact_title_fallback(self):
        """No seed code, but an exact (case/space-insensitive) title match."""
        _anime("200", "Show B")
        counts = self._run(
            catalog=[_entry("GTB", "  show   b ", ["ja-JP"], ["en-US"])],
            mal_to_cr={},
        )

        self.assertEqual((counts["written"], counts["via_title"]), (1, 1))

    def test_no_match_is_skipped(self):
        """Neither seed nor title matches -> unmatched, no row written."""
        item = _anime("300", "Unknown Show")
        counts = self._run(catalog=[], mal_to_cr={})

        self.assertEqual((counts["unmatched"], counts["written"]), (1, 0))
        self.assertFalse(AnimeAvailability.objects.filter(item=item).exists())

    def test_cms_series_fallback_for_seed_miss(self):
        """Seed code present but missing from bulk catalog -> cms/series (D7)."""
        item = _anime("400", "Show D")
        detail = {"audio_locales": ["ja-JP"], "subtitle_locales": ["en-US"]}
        with (
            patch.object(sync.client, "fetch_catalog", return_value=[]),
            patch.object(sync.client, "series", return_value=detail) as mock_series,
            patch.object(sync.resolve, "mal_to_cr", return_value={"400": "GT400"}),
        ):
            counts = sync.backfill_c1("tok")

        mock_series.assert_called_once_with("tok", "GT400")
        self.assertEqual((counts["written"], counts["via_series"]), (1, 1))
        avail = AnimeAvailability.objects.get(item=item)
        self.assertEqual(avail.audio_locales, ["ja-JP"])

    def test_empty_locales_never_blank(self):
        """A matched entry with empty locales is a no-op; a prior row is untouched."""
        item = _anime("500", "Show E")
        AnimeAvailability.objects.create(
            item=item,
            audio_locales=["ja-JP"],
            subtitle_locales=["en-US"],
            source=AvailabilitySource.MANUAL.value,
        )
        counts = self._run(
            catalog=[_entry("GT500", "Show E", [], [])],
            mal_to_cr={"500": "GT500"},
        )

        self.assertEqual((counts["unchanged"], counts["written"]), (1, 0))
        avail = AnimeAvailability.objects.get(item=item)
        self.assertEqual(avail.audio_locales, ["ja-JP"])  # not blanked
        self.assertEqual(avail.subtitle_locales, ["en-US"])
        self.assertEqual(avail.source, AvailabilitySource.MANUAL.value)

    def test_one_failing_title_does_not_sink_the_run(self):
        """A write error on one title is counted, not fatal; others still process."""
        _anime("600", "Show F")
        _anime("700", "Show G")
        with (
            patch.object(
                sync.client,
                "fetch_catalog",
                return_value=[
                    _entry("GT600", "Show F", ["ja-JP"], []),
                    _entry("GT700", "Show G", ["ja-JP"], []),
                ],
            ),
            patch.object(sync.client, "series", return_value=None),
            patch.object(
                sync.resolve,
                "mal_to_cr",
                return_value={"600": "GT600", "700": "GT700"},
            ),
            patch.object(
                sync,
                "upsert_availability",
                side_effect=[RuntimeError("boom"), True],
            ),
        ):
            counts = sync.backfill_c1("tok")

        self.assertEqual(counts["errors"], 1)
        self.assertEqual(counts["written"], 1)
        self.assertEqual(counts["library"], 2)
