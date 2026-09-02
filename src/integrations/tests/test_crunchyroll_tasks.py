"""Tests for the E9b Crunchyroll beat task + helpers (client/sync are mocked)."""

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from app.models import UserMessage, UserMessageLevel
from integrations import tasks

User = get_user_model()

_C2 = {"watchlist": 1, "planning_created": 1, "skipped": 0, "unmatched": 0, "errors": 0}
_C3 = {"series": 1, "written": 1, "unchanged": 0, "skipped": 0, "unmatched": 0,
       "via_season": 0, "multi_season_skipped": 0, "errors": 0}


class ResolveCrUserTests(TestCase):
    """resolve_cr_user picks the configured / sole user, else None."""

    @override_settings(CRUNCHYROLL_USERNAME="")
    def test_sole_user_is_used(self):
        """Exactly one user (personal-fork norm) is picked automatically."""
        user = User.objects.create(username="only")
        self.assertEqual(tasks.resolve_cr_user(), user)

    @override_settings(CRUNCHYROLL_USERNAME="")
    def test_multiple_users_is_ambiguous(self):
        """More than one user + no setting -> None (don't guess)."""
        User.objects.create(username="a")
        User.objects.create(username="b")
        self.assertIsNone(tasks.resolve_cr_user())

    @override_settings(CRUNCHYROLL_USERNAME="picked")
    def test_configured_username_wins(self):
        """The configured username is used even with multiple users."""
        User.objects.create(username="other")
        picked = User.objects.create(username="picked")
        self.assertEqual(tasks.resolve_cr_user(), picked)


class RunCrunchyrollSyncTests(TestCase):
    """run_crunchyroll_sync: profile guard then C2 + C3."""

    def setUp(self):
        """Create the sync target user."""
        self.user = User.objects.create(username="u")

    def test_profile_guard_blocks_when_unconfirmed(self):
        """A token that doesn't confirm the profile raises (no C2/C3 writes)."""
        with (
            patch.object(tasks.client, "mint_token", return_value="tok"),
            patch.object(tasks.client, "account_id", return_value="acct"),
            patch.object(tasks.client, "confirm_profile", return_value=False),
            patch.object(tasks.sync, "sync_c2_status") as mock_c2,
            self.assertRaises(ValueError),
        ):
            tasks.run_crunchyroll_sync(self.user, "etp", "prof")
        mock_c2.assert_not_called()

    def test_happy_path_runs_both(self):
        """A confirmed profile runs C2 + C3 and returns their counts."""
        with (
            patch.object(tasks.client, "mint_token", return_value="tok"),
            patch.object(tasks.client, "account_id", return_value="acct"),
            patch.object(tasks.client, "confirm_profile", return_value=True),
            patch.object(tasks.sync, "sync_c2_status", return_value=_C2),
            patch.object(tasks.sync, "sync_c3_progress", return_value=_C3),
        ):
            result = tasks.run_crunchyroll_sync(self.user, "etp", "prof")
        self.assertEqual(result, {"c2": _C2, "c3": _C3})


class MintWithRenewalTests(TestCase):
    """mint_with_renewal — auto-rotate etp_rt on an auth error (E9.5)."""

    @override_settings(CRUNCHYROLL_ACCOUNT_USERNAME="", CRUNCHYROLL_ACCOUNT_PASSWORD="")
    def test_no_account_credential_reraises_auth_error(self):
        """Without a password configured, an invalid_grant still fails (manual path)."""
        with (
            patch.object(
                tasks.client,
                "mint_token",
                side_effect=ValueError("… invalid_grant …"),
            ) as mock_mint,
            self.assertRaises(ValueError),
        ):
            tasks.mint_with_renewal("etp", profile_id="prof")
        mock_mint.assert_called_once()

    @override_settings(
        CRUNCHYROLL_ACCOUNT_USERNAME="u",
        CRUNCHYROLL_ACCOUNT_PASSWORD="p",  # noqa: S106  (test-only literal)
    )
    def test_renews_on_invalid_grant_and_persists(self):
        """An expired cookie triggers a login, stores the fresh cookie, re-mints."""
        with (
            patch.object(
                tasks.client,
                "mint_token",
                side_effect=[ValueError("… invalid_grant …"), "tok2"],
            ) as mock_mint,
            patch.object(
                tasks.client,
                "account_login",
                return_value={"access_token": "t", "etp_rt": "new-cookie",
                              "etp_rt_vid": "vid"},
            ) as mock_login,
        ):
            token = tasks.mint_with_renewal("old", profile_id="prof")

        self.assertEqual(token, "tok2")
        self.assertEqual(mock_mint.call_count, 2)
        mock_login.assert_called_once_with("u", "p")
        self.assertEqual(tasks.store.resolve_etp_rt(), "new-cookie")

    @override_settings(
        CRUNCHYROLL_ACCOUNT_USERNAME="u",
        CRUNCHYROLL_ACCOUNT_PASSWORD="p",  # noqa: S106  (test-only literal)
    )
    def test_transient_error_is_not_renewed(self):
        """A network/5xx blip re-raises without attempting a login."""
        with (
            patch.object(tasks.client, "mint_token", side_effect=OSError("conn reset")),
            patch.object(tasks.client, "account_login") as mock_login,
            self.assertRaises(OSError),
        ):
            tasks.mint_with_renewal("etp")
        mock_login.assert_not_called()


@override_settings(CRUNCHYROLL_AUTH_FAIL_THRESHOLD=3)
class FailureSignalTests(TestCase):
    """Consecutive auth failures escalate to a persistent error toast."""

    def setUp(self):
        """Create the user and reset the failure streak."""
        self.user = User.objects.create(username="u")
        cache.delete(tasks.CR_FAIL_STREAK_KEY)

    def test_below_threshold_no_message(self):
        """A transient failure only logs (no UserMessage before the threshold)."""
        tasks._record_cr_failure(self.user, "boom")
        tasks._record_cr_failure(self.user, "boom")
        self.assertFalse(UserMessage.objects.exists())

    def test_threshold_raises_error_toast(self):
        """The third consecutive failure surfaces a persistent ERROR message."""
        for _ in range(3):
            tasks._record_cr_failure(self.user, "etp expired")
        msg = UserMessage.objects.get()
        self.assertEqual(msg.level, UserMessageLevel.ERROR.value)
        self.assertIn("3 runs", msg.message)

    def test_clear_resets_streak(self):
        """A success clears the streak so the count restarts from zero."""
        tasks._record_cr_failure(self.user, "x")
        tasks._record_cr_failure(self.user, "x")
        tasks._clear_cr_failure()
        tasks._record_cr_failure(self.user, "x")  # streak now 1, not 3
        self.assertFalse(UserMessage.objects.exists())


class SyncCrunchyrollTaskTests(TestCase):
    """The beat entry point: skip if unconfigured, record failures, clear on success."""

    def setUp(self):
        """Create the user and reset the failure streak."""
        self.user = User.objects.create(username="u")
        cache.delete(tasks.CR_FAIL_STREAK_KEY)

    @override_settings(CRUNCHYROLL_ETP_RT="", CRUNCHYROLL_PROFILE_ID="")
    def test_skips_when_unconfigured(self):
        """No creds -> no-op, no token minted."""
        with patch.object(tasks.client, "mint_token") as mock_mint:
            self.assertIsNone(tasks.sync_crunchyroll())
        mock_mint.assert_not_called()

    @override_settings(
        CRUNCHYROLL_ETP_RT="etp",
        CRUNCHYROLL_PROFILE_ID="prof",
        CRUNCHYROLL_AUTH_FAIL_THRESHOLD=1,
    )
    def test_auth_failure_is_recorded(self):
        """An auth failure is recorded (threshold=1 -> immediate toast), not raised."""
        with patch.object(
            tasks,
            "run_crunchyroll_sync",
            side_effect=ValueError("bad etp"),
        ):
            self.assertIsNone(tasks.sync_crunchyroll())
        self.assertTrue(UserMessage.objects.filter(user=self.user).exists())

    @override_settings(CRUNCHYROLL_ETP_RT="etp", CRUNCHYROLL_PROFILE_ID="prof")
    def test_success_clears_failure_streak(self):
        """A successful run deletes any prior failure streak."""
        cache.set(tasks.CR_FAIL_STREAK_KEY, 2, None)
        with patch.object(
            tasks,
            "run_crunchyroll_sync",
            return_value={"c2": _C2, "c3": _C3},
        ):
            result = tasks.sync_crunchyroll()
        self.assertEqual(result["c3"]["written"], 1)
        self.assertIsNone(cache.get(tasks.CR_FAIL_STREAK_KEY))
