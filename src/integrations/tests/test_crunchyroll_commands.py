"""Tests for the E9a management commands (token + sync are mocked)."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

BACKFILL = "app.management.commands.backfill_crunchyroll_availability"
LIST_CMD = "app.management.commands.list_crunchyroll_profiles"


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
