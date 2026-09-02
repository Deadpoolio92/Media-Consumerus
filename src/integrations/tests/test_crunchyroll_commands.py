"""Tests for the CR management commands (E9a backfill/list + E9b status sync).

Token + sync are mocked; no network.
"""

from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings

BACKFILL = "app.management.commands.backfill_crunchyroll_availability"
LIST_CMD = "app.management.commands.list_crunchyroll_profiles"

User = get_user_model()


class BackfillCommandTests(SimpleTestCase):
    """`backfill_crunchyroll_availability`."""

    @override_settings(CRUNCHYROLL_ETP_RT="")
    def test_missing_etp_rt_raises(self):
        """No credential -> a clear CommandError, no network attempted."""
        with self.assertRaises(CommandError):
            call_command("backfill_crunchyroll_availability")

    @override_settings(CRUNCHYROLL_ETP_RT="etp-value")
    def test_runs_backfill_and_reports(self):
        """Mints a token, runs backfill_c1, prints the summary counts."""
        counts = {
            "library": 5,
            "written": 3,
            "unchanged": 1,
            "unmatched": 1,
            "errors": 0,
            "via_seed": 2,
            "via_title": 1,
            "via_series": 0,
        }
        out = StringIO()
        with (
            patch(f"{BACKFILL}.client.mint_token", return_value="tok"),
            patch(f"{BACKFILL}.sync.backfill_c1", return_value=counts) as mock_backfill,
        ):
            call_command("backfill_crunchyroll_availability", stdout=out)

        mock_backfill.assert_called_once_with("tok")
        self.assertIn("3 written", out.getvalue())

    @override_settings(CRUNCHYROLL_ETP_RT="etp-value")
    def test_auth_failure_raises_commanderror(self):
        """A token mint failure surfaces as a CommandError, not a traceback."""
        with (
            patch(f"{BACKFILL}.client.mint_token", side_effect=ValueError("bad creds")),
            self.assertRaises(CommandError),
        ):
            call_command("backfill_crunchyroll_availability")


class ListProfilesCommandTests(SimpleTestCase):
    """`list_crunchyroll_profiles`."""

    @override_settings(CRUNCHYROLL_ETP_RT="")
    def test_missing_etp_rt_raises(self):
        """No credential -> CommandError."""
        with self.assertRaises(CommandError):
            call_command("list_crunchyroll_profiles")

    @override_settings(CRUNCHYROLL_ETP_RT="etp-value")
    def test_lists_profiles(self):
        """Prints each profile with its id and flags."""
        out = StringIO()
        profile = {"profile_id": "p1", "profile_name": "Me", "is_primary": True}
        with (
            patch(f"{LIST_CMD}.client.mint_token", return_value="tok"),
            patch(f"{LIST_CMD}.client.list_profiles", return_value=[profile]),
        ):
            call_command("list_crunchyroll_profiles", stdout=out)

        output = out.getvalue()
        self.assertIn("p1", output)
        self.assertIn("Me", output)


_C2 = {"watchlist": 2, "planning_created": 1, "skipped": 1, "unmatched": 0, "errors": 0}
_C3 = {"series": 3, "written": 2, "unchanged": 0, "skipped": 0, "unmatched": 1,
       "via_season": 1, "multi_season_skipped": 0, "errors": 0}


class SyncStatusCommandTests(TestCase):
    """`sync_crunchyroll_status` (E9b manual one-shot)."""

    @override_settings(CRUNCHYROLL_ETP_RT="", CRUNCHYROLL_PROFILE_ID="prof")
    def test_missing_etp_rt_raises(self):
        """No credential -> CommandError, no network."""
        with self.assertRaises(CommandError):
            call_command("sync_crunchyroll_status")

    @override_settings(CRUNCHYROLL_ETP_RT="etp", CRUNCHYROLL_PROFILE_ID="")
    def test_missing_profile_id_raises(self):
        """No confirmed-profile target -> CommandError (won't risk a wrong write)."""
        with self.assertRaises(CommandError):
            call_command("sync_crunchyroll_status")

    @override_settings(CRUNCHYROLL_ETP_RT="etp", CRUNCHYROLL_PROFILE_ID="prof")
    def test_runs_and_reports(self):
        """Resolves the user, runs the shared sync, prints C2/C3 counts."""
        User.objects.create(username="solo")
        out = StringIO()
        with patch(
            "integrations.tasks.run_crunchyroll_sync",
            return_value={"c2": _C2, "c3": _C3},
        ) as mock_run:
            call_command("sync_crunchyroll_status", stdout=out)

        mock_run.assert_called_once()
        output = out.getvalue()
        self.assertIn("1 new Planning", output)
        self.assertIn("2 written", output)

    @override_settings(CRUNCHYROLL_ETP_RT="etp", CRUNCHYROLL_PROFILE_ID="prof")
    def test_sync_failure_raises_commanderror(self):
        """An auth/profile failure surfaces as a CommandError, not a traceback."""
        User.objects.create(username="solo")
        with (
            patch(
                "integrations.tasks.run_crunchyroll_sync",
                side_effect=ValueError("profile could not be confirmed"),
            ),
            self.assertRaises(CommandError),
        ):
            call_command("sync_crunchyroll_status")


class FlushCrResolveCacheCommandTests(SimpleTestCase):
    """`flush_cr_resolve_cache` — evicts outage-poisoned cr:resolve:* keys once."""

    def setUp(self):
        """Isolate the cache per test."""
        cache.clear()

    def test_flushes_only_cr_resolve_keys(self):
        """Deletes every cr:resolve:* key and leaves other cache keys alone."""
        cache.set("cr:resolve:title:kaguya sama love is war", "104578")
        cache.set("cr:resolve:code:GTSOMECODE", "")
        cache.set("unrelated:key", "keep-me")

        out = StringIO()
        call_command("flush_cr_resolve_cache", stdout=out)

        self.assertIsNone(cache.get("cr:resolve:title:kaguya sama love is war"))
        self.assertIsNone(cache.get("cr:resolve:code:GTSOMECODE"))
        self.assertEqual(cache.get("unrelated:key"), "keep-me")
        self.assertIn("Flushed 2 cr:resolve:* cache key", out.getvalue())

    def test_dry_run_does_not_delete(self):
        """--dry-run reports the poisoned keys without removing them."""
        cache.set("cr:resolve:title:some show", "")
        out = StringIO()
        call_command("flush_cr_resolve_cache", "--dry-run", stdout=out)
        self.assertEqual(cache.get("cr:resolve:title:some show"), "")
        self.assertIn("DRY RUN", out.getvalue())
