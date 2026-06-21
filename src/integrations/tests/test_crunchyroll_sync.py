"""Tests for the CR sync (E9a C1 backfill + E9b C2/C3). All CR network is mocked."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from app.mixins import disable_fetch_releases
from app.models import (
    Anime,
    AnimeAvailability,
    AvailabilitySource,
    Item,
    MediaTypes,
    Sources,
    Status,
)
from integrations.crunchyroll import sync

User = get_user_model()


def _meta(title="Show", max_progress=12):
    """Catalog metadata shape returned by the patched provider lookup."""
    return {
        "title": title,
        "image": "http://example.com/i.jpg",
        "max_progress": max_progress,
    }


def _patch_metadata(**kwargs):
    """Patch the provider metadata lookup used by both the model and the CR sync."""
    return patch(
        "app.providers.services.get_media_metadata",
        return_value=_meta(**kwargs),
    )


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


class AdvanceProgressTests(TestCase):
    """The shared forward-only / never-downgrade advancement rule (E9b)."""

    def setUp(self):
        """Create the sync target user."""
        self.user = User.objects.create(username="cr-user")
        self.item = _anime("100", "Show A")

    def _advance(self, furthest, *, max_progress=12):
        with disable_fetch_releases(), _patch_metadata(max_progress=max_progress):
            return sync._advance_progress(self.user, self.item, furthest)

    def _anime_row(self):
        return Anime.objects.get(item=self.item, user=self.user)

    def test_creates_in_progress_row(self):
        """No row + real progress -> a fresh In progress row at that episode."""
        self.assertEqual(self._advance(5), "written")
        row = self._anime_row()
        self.assertEqual((row.progress, row.status), (5, Status.IN_PROGRESS.value))

    def test_creates_completed_at_max(self):
        """Furthest at the episode count -> Completed (capped to max)."""
        self.assertEqual(self._advance(99, max_progress=12), "written")
        row = self._anime_row()
        self.assertEqual((row.progress, row.status), (12, Status.COMPLETED.value))

    def test_zero_progress_creates_nothing(self):
        """No row + no real progress -> skipped, no row created."""
        self.assertEqual(self._advance(0), "skipped")
        self.assertFalse(Anime.objects.filter(item=self.item).exists())

    def test_never_downgrades_completed(self):
        """A Completed row is never touched by a lower CR progress."""
        with disable_fetch_releases(), _patch_metadata(max_progress=12):
            Anime.objects.create(
                item=self.item, user=self.user,
                status=Status.COMPLETED.value, progress=12,
            )
        self.assertEqual(self._advance(3), "skipped")
        self.assertEqual(self._anime_row().status, Status.COMPLETED.value)

    def test_skips_paused_and_dropped(self):
        """A user's Paused/Dropped row is manual intent — left alone."""
        for status in (Status.PAUSED.value, Status.DROPPED.value):
            with disable_fetch_releases(), _patch_metadata(max_progress=12):
                Anime.objects.update_or_create(
                    item=self.item, user=self.user,
                    defaults={"status": status, "progress": 2},
                )
            self.assertEqual(self._advance(9), "skipped")
            self.assertEqual(self._anime_row().status, status)

    def test_forward_only_does_not_reduce(self):
        """A furthest below current progress is a no-op (no rewind)."""
        with disable_fetch_releases(), _patch_metadata(max_progress=12):
            Anime.objects.create(
                item=self.item, user=self.user,
                status=Status.IN_PROGRESS.value, progress=8,
            )
        self.assertEqual(self._advance(3), "unchanged")
        self.assertEqual(self._anime_row().progress, 8)

    def test_planning_promoted_to_in_progress(self):
        """A Planning row with real CR progress becomes In progress."""
        with disable_fetch_releases(), _patch_metadata(max_progress=12):
            Anime.objects.create(
                item=self.item, user=self.user,
                status=Status.PLANNING.value, progress=0,
            )
        self.assertEqual(self._advance(4), "written")
        row = self._anime_row()
        self.assertEqual((row.progress, row.status), (4, Status.IN_PROGRESS.value))


class SyncC2StatusTests(TestCase):
    """Watchlist -> Planning for untracked titles only."""

    def setUp(self):
        """Create the sync target user."""
        self.user = User.objects.create(username="cr-user")

    def _run(self, *, watchlist, cr_to_mal):
        with (
            disable_fetch_releases(),
            patch.object(sync.client, "fetch_watchlist", return_value=watchlist),
            patch.object(sync.resolve, "cr_code_to_mal", side_effect=cr_to_mal),
            _patch_metadata(),
        ):
            return sync.sync_c2_status("tok", "acct", self.user)

    def test_creates_planning_for_new_title(self):
        """A resolvable watchlist title with no row -> a Planning row."""
        counts = self._run(
            watchlist=[{"series_id": "GT1", "title": "Show A"}],
            cr_to_mal=lambda *_:"100",
        )
        self.assertEqual(counts["planning_created"], 1)
        row = Anime.objects.get(item__media_id="100", user=self.user)
        self.assertEqual(row.status, Status.PLANNING.value)

    def test_existing_row_is_left_untouched(self):
        """An already-tracked title is skipped (C3 drives transitions, not C2)."""
        item = _anime("200", "Show B")
        Anime.objects.create(
            item=item, user=self.user, status=Status.IN_PROGRESS.value, progress=3,
        )
        counts = self._run(
            watchlist=[{"series_id": "GT2", "title": "Show B"}],
            cr_to_mal=lambda *_:"200",
        )
        self.assertEqual((counts["skipped"], counts["planning_created"]), (1, 0))
        self.assertEqual(
            Anime.objects.get(item=item, user=self.user).status,
            Status.IN_PROGRESS.value,
        )

    def test_unresolvable_series_counted(self):
        """A watchlist series that can't resolve to MAL is counted, not written."""
        counts = self._run(
            watchlist=[{"series_id": "GTX", "title": "Mystery"}],
            cr_to_mal=lambda *_:None,
        )
        self.assertEqual((counts["unmatched"], counts["planning_created"]), (1, 0))


class SyncC3ProgressTests(TestCase):
    """History -> forward progress, incl. the D3 multi-season hybrid."""

    def setUp(self):
        """Create the sync target user."""
        self.user = User.objects.create(username="cr-user")

    def _run(self, *, history, seasons=None, cr_to_mal=None, title_to_mal=None):
        cr_to_mal = cr_to_mal or (lambda *_: None)
        title_to_mal = title_to_mal or (lambda *_: None)
        with (
            disable_fetch_releases(),
            patch.object(sync.client, "fetch_history", return_value=history),
            patch.object(sync.client, "seasons", return_value=seasons or []),
            patch.object(sync.resolve, "cr_code_to_mal", side_effect=cr_to_mal),
            patch.object(
                sync.resolve, "resolve_title_to_mal", side_effect=title_to_mal,
            ),
            _patch_metadata(),
        ):
            return sync.sync_c3_progress("tok", "acct", self.user)

    def test_single_season_seed_write(self):
        """A season-1 series resolves off the seed and writes furthest progress."""
        history = [
            {"series_id": "GT1", "season_number": 1, "episode_number": 4, "title": "A"},
            {"series_id": "GT1", "season_number": 1, "episode_number": 7, "title": "A"},
        ]
        counts = self._run(history=history, cr_to_mal=lambda *_: "100")
        self.assertEqual(counts["written"], 1)
        row = Anime.objects.get(item__media_id="100", user=self.user)
        self.assertEqual(row.progress, 7)  # furthest of the two history rows

    def test_multi_season_resolves_via_season_title(self):
        """A season>1 row resolves per-season via the seasons endpoint title."""
        history = [
            {"series_id": "GT9", "season_number": 2,
             "episode_number": 5, "title": "Fr"},
        ]
        counts = self._run(
            history=history,
            seasons=[{"season_number": 2, "title": "Frieren S2"}],
            title_to_mal=lambda t: "555" if t == "Frieren S2" else None,
        )
        self.assertEqual((counts["via_season"], counts["written"]), (1, 1))
        self.assertTrue(
            Anime.objects.filter(item__media_id="555", user=self.user).exists(),
        )

    def test_multi_season_unresolved_is_reported_not_written(self):
        """A season>1 title that won't resolve is skip+report, never guess-written."""
        history = [
            {"series_id": "GT9", "season_number": 3, "episode_number": 2, "title": "X"},
        ]
        counts = self._run(
            history=history,
            seasons=[{"season_number": 3, "title": "Unknown S3"}],
            title_to_mal=lambda *_: None,
        )
        self.assertEqual(counts["multi_season_skipped"], 1)
        self.assertEqual(counts["written"], 0)
        self.assertEqual(Anime.objects.count(), 0)

    def test_season_one_unresolved_counted_unmatched(self):
        """A season-1 series the seed/Jikan can't place is counted unmatched."""
        history = [
            {"series_id": "GTX", "season_number": 1, "episode_number": 3, "title": "Q"},
        ]
        counts = self._run(history=history, cr_to_mal=lambda *_: None)
        self.assertEqual((counts["unmatched"], counts["written"]), (1, 0))
