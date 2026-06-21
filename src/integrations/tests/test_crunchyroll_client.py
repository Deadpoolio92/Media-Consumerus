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
