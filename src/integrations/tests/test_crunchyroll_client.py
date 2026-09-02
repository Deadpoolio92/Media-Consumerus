"""Offline tests for the Crunchyroll client (E9a surface). All network is mocked.

Fixtures are trimmed real-shape CR JSON; the locale tests pin the top-level-vs-nested
nuance that bit v1 (cms/series top-level vs browse nested under series_metadata).
"""

from unittest.mock import MagicMock, patch

import requests
from django.test import SimpleTestCase, override_settings

from integrations.crunchyroll import client


class BasicAuthTests(SimpleTestCase):
    """The unofficial Basic-auth credential is required config, not guessed."""

    @override_settings(CRUNCHYROLL_BASIC_AUTH="")
    def test_unset_raises(self):
        """An unset credential fails loudly with an actionable message."""
        with self.assertRaises(ValueError):
            client._basic_auth()

    @override_settings(CRUNCHYROLL_BASIC_AUTH="abc123==")
    def test_bare_value_gets_basic_prefix(self):
        """A bare token is normalized to a 'Basic ...' header value."""
        self.assertEqual(client._basic_auth(), "Basic abc123==")

    @override_settings(CRUNCHYROLL_BASIC_AUTH="Basic abc123==")
    def test_prefixed_value_passthrough(self):
        """An already-prefixed value is left as-is (case-insensitive check)."""
        self.assertEqual(client._basic_auth(), "Basic abc123==")


@override_settings(CRUNCHYROLL_BASIC_AUTH="Basic test==")
class MintTokenTests(SimpleTestCase):
    """etp_rt -> access token exchange."""

    def test_returns_access_token(self):
        """A well-formed token response yields the access_token string."""
        with patch.object(
            client.services,
            "api_request",
            return_value={"access_token": "tok-123", "token_type": "Bearer"},
        ) as mock_req:
            token = client.mint_token("etp-rt-value")

        self.assertEqual(token, "tok-123")
        # POSTed the etp_rt grant with the required device fields + cookie + basic auth.
        kwargs = mock_req.call_args[1]
        self.assertEqual(kwargs["data"]["grant_type"], "etp_rt_cookie")
        self.assertIn("device_id", kwargs["data"])
        self.assertIn("device_type", kwargs["data"])
        self.assertEqual(kwargs["headers"]["Cookie"], "etp_rt=etp-rt-value")
        self.assertEqual(kwargs["headers"]["Authorization"], "Basic test==")

    def test_missing_access_token_raises(self):
        """A 200 with no access_token is a hard error, not a silent empty token."""
        with (
            patch.object(client.services, "api_request", return_value={}),
            self.assertRaises(ValueError),
        ):
            client.mint_token("etp-rt-value")


class ExtractLocalesTests(SimpleTestCase):
    """The top-level vs nested locale fallback chain."""

    def test_top_level_wins(self):
        """cms/series shape: locales sit at the top level."""
        node = {"audio_locales": ["ja-JP", "en-US"]}
        self.assertEqual(
            client._extract_locales(node, "audio_locales"),
            ["ja-JP", "en-US"],
        )

    def test_nested_series_metadata(self):
        """Browse shape: locales nested under series_metadata."""
        node = {"series_metadata": {"subtitle_locales": ["en-US", "es-419"]}}
        self.assertEqual(
            client._extract_locales(node, "subtitle_locales"),
            ["en-US", "es-419"],
        )

    def test_nested_movie_listing_metadata(self):
        """Browse shape for movies: locales nested under movie_listing_metadata."""
        node = {"movie_listing_metadata": {"audio_locales": ["ja-JP"]}}
        self.assertEqual(client._extract_locales(node, "audio_locales"), ["ja-JP"])

    def test_missing_returns_empty_list(self):
        """No locales anywhere -> empty list; non-dict -> empty list."""
        self.assertEqual(client._extract_locales({}, "audio_locales"), [])
        self.assertEqual(client._extract_locales(None, "audio_locales"), [])


@override_settings(CRUNCHYROLL_BASIC_AUTH="Basic test==")
class FetchCatalogTests(SimpleTestCase):
    """Browse catalog parse (the C1 match source)."""

    def test_parses_entries_and_drops_idless(self):
        """Entries are normalized; an entry with no id is dropped."""
        payload = {
            "data": [
                {
                    "id": "GT001",
                    "title": "Frieren",
                    "type": "series",
                    "series_metadata": {
                        "audio_locales": ["ja-JP", "en-US"],
                        "subtitle_locales": ["en-US", "es-419"],
                    },
                },
                {"title": "No ID — skipped", "type": "series"},
            ],
        }
        with patch.object(client.services, "api_request", return_value=payload):
            entries = client.fetch_catalog("tok")

        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["code"], "GT001")
        self.assertEqual(entry["title"], "Frieren")
        self.assertEqual(entry["audio_locales"], ["ja-JP", "en-US"])
        self.assertEqual(entry["subtitle_locales"], ["en-US", "es-419"])

    def test_empty_catalog(self):
        """A payload with no data yields no entries (no crash)."""
        with patch.object(client.services, "api_request", return_value={}):
            self.assertEqual(client.fetch_catalog("tok"), [])

    def test_paginates_until_short_page(self):
        """A full page is followed by another request; a short page ends paging."""
        full = {
            "data": [
                {"id": f"C{i}", "title": f"T{i}", "type": "series"}
                for i in range(client.CATALOG_PAGE_SIZE)
            ],
        }
        last = {"data": [{"id": "LAST", "title": "Last", "type": "series"}]}
        with patch.object(
            client.services,
            "api_request",
            side_effect=[full, last],
        ) as mock_req:
            entries = client.fetch_catalog("tok")

        self.assertEqual(mock_req.call_count, 2)
        self.assertEqual(len(entries), client.CATALOG_PAGE_SIZE + 1)


@override_settings(CRUNCHYROLL_BASIC_AUTH="Basic test==")
class SeriesFallbackTests(SimpleTestCase):
    """cms/series fallback for titles missing from browse."""

    def test_top_level_locales(self):
        """cms/series returns locales at the top level."""
        payload = {
            "data": [{"audio_locales": ["ja-JP"], "subtitle_locales": ["en-US"]}],
        }
        with patch.object(client.services, "api_request", return_value=payload):
            result = client.series("tok", "GT999")

        self.assertEqual(
            result,
            {"audio_locales": ["ja-JP"], "subtitle_locales": ["en-US"]},
        )

    def test_nested_locales_fallback(self):
        """cms/series can also nest under series_metadata; fallback finds them."""
        payload = {"data": [{"series_metadata": {"audio_locales": ["ja-JP", "de-DE"]}}]}
        with patch.object(client.services, "api_request", return_value=payload):
            result = client.series("tok", "GT999")

        self.assertEqual(result["audio_locales"], ["ja-JP", "de-DE"])
        self.assertEqual(result["subtitle_locales"], [])

    def test_empty_data_returns_none(self):
        """No data array -> None (skip the title, don't crash)."""
        with patch.object(client.services, "api_request", return_value={"data": []}):
            self.assertIsNone(client.series("tok", "GT999"))

    def test_404_is_a_clean_skip(self):
        """A stale seed code (404) returns None, not an error."""
        err = requests.exceptions.HTTPError(response=MagicMock(status_code=404))
        with patch.object(client.services, "api_request", side_effect=err):
            self.assertIsNone(client.series("tok", "GONE"))


class ListProfilesTests(SimpleTestCase):
    """multiprofile read (E9 setup helper)."""

    def test_returns_profiles(self):
        """Profiles list is returned from the payload."""
        payload = {
            "profiles": [
                {"profile_id": "p1", "profile_name": "Me", "is_primary": True},
            ],
        }
        with patch.object(client.services, "api_request", return_value=payload):
            profiles = client.list_profiles("tok")
        self.assertEqual(profiles[0]["profile_id"], "p1")

    def test_no_profiles_key(self):
        """A payload missing 'profiles' yields an empty list (no crash)."""
        with patch.object(client.services, "api_request", return_value={}):
            self.assertEqual(client.list_profiles("tok"), [])


@override_settings(CRUNCHYROLL_BASIC_AUTH="Basic test==")
class AccountLoginTests(SimpleTestCase):
    """account_login — the E9.5 etp_rt rotation path."""

    def _login_response(self, cookies):
        """Build a fake session.post response carrying the given cookies."""
        resp = MagicMock()
        resp.json.return_value = {"access_token": "tok-login", "token_type": "Bearer"}
        resp.cookies.get.side_effect = cookies.get
        return resp

    def test_returns_fresh_etp_rt_and_access_token(self):
        """Reads the rotated etp_rt from the login Set-Cookie and the body token."""
        resp = self._login_response({"etp_rt": "new-cookie", "etp_rt_vid": "vid"})
        with patch.object(
            client.services.session,
            "post",
            return_value=resp,
        ) as mock_post:
            result = client.account_login("user@x.com", "secret")

        self.assertEqual(result["etp_rt"], "new-cookie")
        self.assertEqual(result["etp_rt_vid"], "vid")
        self.assertEqual(result["access_token"], "tok-login")
        called = mock_post.call_args
        self.assertEqual(called[0][0], client.LOGIN_URL)
        self.assertEqual(called[1]["data"]["grant_type"], "password")
        self.assertEqual(called[1]["data"]["auth_type"], "etp")
        self.assertEqual(called[1]["data"]["username"], "user@x.com")
        self.assertEqual(called[1]["data"]["password"], "secret")
        self.assertIn("device_id", called[1]["data"])
        self.assertEqual(called[1]["headers"]["Authorization"], "Basic test==")

    def test_missing_etp_rt_cookie_raises(self):
        """A login response without an etp_rt cookie is a hard error."""
        resp = self._login_response({})
        with (
            patch.object(client.services.session, "post", return_value=resp),
            self.assertRaises(ValueError),
        ):
            client.account_login("user@x.com", "secret")

    def test_missing_access_token_raises(self):
        """A login response with an etp_rt but no token is a hard error."""
        resp = self._login_response({"etp_rt": "new-cookie"})
        resp.json.return_value = {}
        with (
            patch.object(client.services.session, "post", return_value=resp),
            self.assertRaises(ValueError),
        ):
            client.account_login("user@x.com", "secret")


class IsAuthErrorTests(SimpleTestCase):
    """is_auth_error — the E9.5 renewal trigger detection."""

    def test_invalid_grant_is_an_auth_error(self):
        """An expired etp_rt (invalid_grant) is renewable."""
        self.assertTrue(client.is_auth_error(ValueError("… (400): invalid_grant …")))

    def test_transient_errors_are_not_auth_errors(self):
        """Network/5xx/429 blips are not credential problems (don't re-login)."""
        self.assertFalse(client.is_auth_error(OSError("connection refused")))
        self.assertFalse(client.is_auth_error(ValueError("… (429): rate limited")))


@override_settings(CRUNCHYROLL_BASIC_AUTH="Basic test==")
class MintTokenProfileTests(SimpleTestCase):
    """E9b: a profile-bound token sends the profile_id form field."""

    def test_profile_id_is_sent_when_given(self):
        """mint_token(..., profile_id) adds the profile bind field to the grant."""
        with patch.object(
            client.services,
            "api_request",
            return_value={"access_token": "tok"},
        ) as mock_req:
            client.mint_token("etp", profile_id="prof-9")
        self.assertEqual(mock_req.call_args[1]["data"]["profile_id"], "prof-9")

    def test_profile_id_omitted_by_default(self):
        """E9a's catalog-wide call sends no profile_id (unchanged behavior)."""
        with patch.object(
            client.services,
            "api_request",
            return_value={"access_token": "tok"},
        ) as mock_req:
            client.mint_token("etp")
        self.assertNotIn("profile_id", mock_req.call_args[1]["data"])


class AccountIdTests(SimpleTestCase):
    """E9b: the watchlist/history account path segment."""

    def test_returns_account_id(self):
        """accounts/v1/me yields the account_id."""
        with patch.object(
            client.services,
            "api_request",
            return_value={"account_id": "acct-1"},
        ):
            self.assertEqual(client.account_id("tok"), "acct-1")

    def test_missing_account_id_raises(self):
        """A response with no account_id is a hard error."""
        with (
            patch.object(client.services, "api_request", return_value={}),
            self.assertRaises(ValueError),
        ):
            client.account_id("tok")


class ConfirmProfileTests(SimpleTestCase):
    """E9b: the mandatory shared-account guard."""

    def _profiles(self, profiles):
        return patch.object(
            client.services,
            "api_request",
            return_value={"profiles": profiles},
        )

    def test_selected_matches_expected(self):
        """The selected profile equals the configured id -> guard passes."""
        with self._profiles(
            [
                {"profile_id": "mine", "is_selected": True},
                {"profile_id": "other", "is_selected": False},
            ],
        ):
            self.assertTrue(client.confirm_profile("tok", "mine"))

    def test_selected_is_someone_else(self):
        """A selected profile that isn't ours -> guard fails (caller skips)."""
        with self._profiles([{"profile_id": "other", "is_selected": True}]):
            self.assertFalse(client.confirm_profile("tok", "mine"))

    def test_no_selected_profile(self):
        """No profile flagged selected -> guard fails."""
        with self._profiles([{"profile_id": "mine", "is_selected": False}]):
            self.assertFalse(client.confirm_profile("tok", "mine"))

    def test_blank_expected_id_fails_closed(self):
        """An unconfigured CRUNCHYROLL_PROFILE_ID fails the guard, no API call."""
        with patch.object(client.services, "api_request") as mock_req:
            self.assertFalse(client.confirm_profile("tok", ""))
        mock_req.assert_not_called()


class FetchWatchlistTests(SimpleTestCase):
    """E9b: watchlist -> series ids (anime only)."""

    def test_extracts_episode_and_series_panels_drops_movies(self):
        """Episode + series panels yield series ids; a movie panel is dropped."""
        payload = {
            "data": [
                {
                    "panel": {
                        "type": "episode",
                        "episode_metadata": {
                            "series_id": "GT1",
                            "series_title": "Show One",
                        },
                    },
                },
                {"panel": {"type": "series", "id": "GT2", "title": "Show Two"}},
                {"panel": {"type": "movie", "movie_listing_metadata": {}}},
            ],
        }
        with patch.object(client.services, "api_request", return_value=payload):
            entries = client.fetch_watchlist("tok", "acct")

        self.assertEqual(
            entries,
            [
                {"series_id": "GT1", "title": "Show One"},
                {"series_id": "GT2", "title": "Show Two"},
            ],
        )

    def test_empty_watchlist(self):
        """No data -> no entries."""
        with patch.object(client.services, "api_request", return_value={}):
            self.assertEqual(client.fetch_watchlist("tok", "acct"), [])


class FetchHistoryTests(SimpleTestCase):
    """E9b: watch-history -> normalized progress rows."""

    def test_parses_top_level_and_nested_shapes(self):
        """series_id/season/episode are read from the row or panel.episode_metadata."""
        payload = {
            "data": [
                {
                    "series_id": "GT1",
                    "season_number": 1,
                    "episode_number": 12,
                    "series_title": "Show One",
                },
                {
                    "panel": {
                        "episode_metadata": {
                            "series_id": "GT2",
                            "season_number": 2,
                            "episode_number": 5,
                            "series_title": "Show Two",
                        },
                    },
                },
                {"panel": {"episode_metadata": {}}},  # no series id -> dropped
            ],
        }
        with patch.object(client.services, "api_request", return_value=payload):
            rows = client.fetch_history("tok", "acct")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["series_id"], "GT1")
        self.assertEqual(rows[0]["episode_number"], 12)
        self.assertEqual(rows[1]["series_id"], "GT2")
        self.assertEqual(rows[1]["season_number"], 2)

    def test_season_episode_default_when_absent(self):
        """A row with only a series id defaults to season 1 / episode 0."""
        payload = {"data": [{"series_id": "GT9"}]}
        with patch.object(client.services, "api_request", return_value=payload):
            rows = client.fetch_history("tok", "acct")
        self.assertEqual((rows[0]["season_number"], rows[0]["episode_number"]), (1, 0))


class SeasonsTests(SimpleTestCase):
    """E9b: per-season list for the multi-season resolve (D3)."""

    def test_returns_seasons(self):
        """cms/series/{code}/seasons yields season_number + title pairs."""
        payload = {
            "data": [
                {"season_number": 1, "title": "Season 1"},
                {"season_number": 2, "title": "Season 2: Sequel"},
            ],
        }
        with patch.object(client.services, "api_request", return_value=payload):
            result = client.seasons("tok", "GT1")
        self.assertEqual(result[1], {"season_number": 2, "title": "Season 2: Sequel"})

    def test_404_yields_empty(self):
        """A series with no seasons endpoint (404) yields [] (caller skips)."""
        err = requests.exceptions.HTTPError(response=MagicMock(status_code=404))
        with patch.object(client.services, "api_request", side_effect=err):
            self.assertEqual(client.seasons("tok", "GONE"), [])


class TokenRefreshTests(SimpleTestCase):
    """Token — a self-refreshing access token (E9.5, mid-run 401 recovery)."""

    def test_auth_headers_uses_token_value(self):
        """_auth_headers reads the current value from a Token."""
        tok = client.Token("abc", lambda: "def")
        self.assertEqual(client._auth_headers(tok)["Authorization"], "Bearer abc")

    def test_content_call_refreshes_on_401_and_retries(self):
        """A 401 on a content call re-mints the token and retries once."""
        err = requests.exceptions.HTTPError(response=MagicMock(status_code=401))
        ok = {"data": [{"season_number": 1, "title": "S1"}]}
        refreshed = []

        def refresh():
            refreshed.append(1)
            return "new-token"

        tok = client.Token("old", refresh)
        with patch.object(
            client.services,
            "api_request",
            side_effect=[err, ok],
        ) as mock_req:
            result = client.seasons(tok, "GT1")

        self.assertEqual(result[0]["title"], "S1")
        self.assertEqual(mock_req.call_count, 2)
        self.assertEqual(refreshed, [1])
        # The retry used the freshly-minted token.
        self.assertEqual(
            mock_req.call_args[1]["headers"]["Authorization"],
            "Bearer new-token",
        )

    def test_plain_string_token_does_not_refresh(self):
        """A plain str token (no refresh) surfaces the 401 as a ValueError."""
        err = requests.exceptions.HTTPError(response=MagicMock(status_code=401))
        with (
            patch.object(client.services, "api_request", side_effect=err),
            self.assertRaises(ValueError),
        ):
            client.seasons("old", "GT1")
