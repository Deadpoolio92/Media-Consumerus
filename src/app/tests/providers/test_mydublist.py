from json import JSONDecodeError
from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from app.providers import mydublist

# The on-add autouse stub (tests/conftest.py) rebinds the module attribute
# ``mydublist.get_locales`` to a no-op. Capture the real function here so the
# get_locales tests below exercise the actual implementation, not the stub.
from app.providers.mydublist import get_locales as real_get_locales


def _fake_api_request(payloads):
    """Build an api_request side effect that serves per-language payloads by URL.

    URLs look like ``.../<confidence>/dubbed_<lang>.json``; any language not in
    ``payloads`` returns an empty (but well-formed) file.
    """

    def _side_effect(provider, method, url, *args, **kwargs):  # noqa: ARG001
        lang = url.rsplit("dubbed_", 1)[1].removesuffix(".json")
        return payloads.get(lang, {"language": lang, "dubbed": [], "partial": []})

    return _side_effect


# english -> en-US, german -> de-DE. media 1 is dubbed in both; 5 english-only;
# 15 is an english *partial* (merged in as available).
SAMPLE_PAYLOADS = {
    "english": {"language": "English", "dubbed": [1, 5], "partial": [15]},
    "german": {"language": "German", "dubbed": [1], "partial": []},
}


class NormalizeLocalesTests(SimpleTestCase):
    """Test normalize_locales dedupe + stable ordering."""

    def test_empty_returns_empty(self):
        """No codes in -> empty list out."""
        self.assertEqual(mydublist.normalize_locales([]), [])

    def test_known_codes_ordered_by_languages_map(self):
        """Known codes come out in languages.LOCALE_DISPLAY order."""
        self.assertEqual(
            mydublist.normalize_locales(["de-DE", "en-US", "ja-JP"]),
            ["ja-JP", "en-US", "de-DE"],
        )

    def test_unknown_codes_pass_through_after_known(self):
        """Unmapped codes are kept (visible) and appended after known ones."""
        self.assertEqual(
            mydublist.normalize_locales(["zz-ZZ", "en-US"]),
            ["en-US", "zz-ZZ"],
        )

    def test_duplicates_collapse(self):
        """Repeated codes collapse to one (dubbed + partial overlap)."""
        self.assertEqual(
            mydublist.normalize_locales(["en-US", "ja-JP", "en-US", "ja-JP"]),
            ["ja-JP", "en-US"],
        )

    def test_unknown_duplicates_collapse_in_first_seen_order(self):
        """Unknown codes dedupe and keep their first-seen order."""
        self.assertEqual(
            mydublist.normalize_locales(["da-DK", "en-US", "da-DK"]),
            ["en-US", "da-DK"],
        )

    def test_falsy_entries_skipped(self):
        """Empty/None entries are dropped, not rendered."""
        self.assertEqual(
            mydublist.normalize_locales(["", "en-US", None]),
            ["en-US"],
        )


class ResolveConfidenceTests(SimpleTestCase):
    """Test confidence-tier resolution + validation."""

    @override_settings(MYDUBLIST_CONFIDENCE="normal")
    def test_none_uses_configured_setting(self):
        """A None argument falls back to settings.MYDUBLIST_CONFIDENCE."""
        self.assertEqual(mydublist.resolve_confidence(), "normal")

    def test_explicit_valid_tier_passes_through(self):
        """A valid explicit tier is returned unchanged."""
        self.assertEqual(mydublist.resolve_confidence("very-high"), "very-high")

    def test_invalid_tier_raises(self):
        """An unknown tier fails loudly rather than 404-ing later."""
        with self.assertRaises(ValueError):
            mydublist.resolve_confidence("bogus")


class FetchDatasetTests(SimpleTestCase):
    """Test the download + invert + cache behaviour of fetch_dataset."""

    def setUp(self):
        """Start each test with an empty cache and clean up after."""
        cache.clear()
        self.addCleanup(cache.clear)

    def test_inverts_and_downloads_every_language(self):
        """All 27 language files are fetched and inverted to {mal_id: [codes]}."""
        with patch(
            "app.providers.mydublist.services.api_request",
            side_effect=_fake_api_request(SAMPLE_PAYLOADS),
        ) as mock_req:
            data = mydublist.fetch_dataset(confidence="high", force_refresh=True)

        self.assertEqual(mock_req.call_count, len(mydublist.LANG_TO_LOCALE))
        self.assertEqual(
            data,
            {"1": ["en-US", "de-DE"], "5": ["en-US"], "15": ["en-US"]},
        )

    def test_cache_hit_skips_download(self):
        """A second call without force_refresh is served from cache."""
        with patch(
            "app.providers.mydublist.services.api_request",
            side_effect=_fake_api_request(SAMPLE_PAYLOADS),
        ):
            first = mydublist.fetch_dataset(confidence="high", force_refresh=True)

        with patch("app.providers.mydublist.services.api_request") as mock_req:
            second = mydublist.fetch_dataset(confidence="high")

        mock_req.assert_not_called()
        self.assertEqual(first, second)

    def test_force_refresh_redownloads(self):
        """force_refresh bypasses a warm cache and re-downloads."""
        with patch(
            "app.providers.mydublist.services.api_request",
            side_effect=_fake_api_request(SAMPLE_PAYLOADS),
        ):
            mydublist.fetch_dataset(confidence="high", force_refresh=True)

        with patch(
            "app.providers.mydublist.services.api_request",
            side_effect=_fake_api_request(SAMPLE_PAYLOADS),
        ) as mock_req:
            mydublist.fetch_dataset(confidence="high", force_refresh=True)

        self.assertEqual(mock_req.call_count, len(mydublist.LANG_TO_LOCALE))

    def test_http_error_propagates_and_caches_nothing(self):
        """A network/HTTP error aborts the whole fetch with nothing cached."""
        with (
            patch(
                "app.providers.mydublist.services.api_request",
                side_effect=requests.exceptions.HTTPError("500"),
            ),
            self.assertRaises(requests.exceptions.HTTPError),
        ):
            mydublist.fetch_dataset(confidence="high", force_refresh=True)

        self.assertIsNone(cache.get("mydublist_dataset_high"))

    def test_bad_json_propagates_and_caches_nothing(self):
        """A JSON decode error propagates; no partial dataset is cached."""
        with (
            patch(
                "app.providers.mydublist.services.api_request",
                side_effect=JSONDecodeError("Expecting value", "", 0),
            ),
            self.assertRaises(ValueError),
        ):
            mydublist.fetch_dataset(confidence="high", force_refresh=True)

        self.assertIsNone(cache.get("mydublist_dataset_high"))

    def test_schema_drift_raises_and_caches_nothing(self):
        """A file missing the 'dubbed' key is treated as schema drift."""
        with (
            patch(
                "app.providers.mydublist.services.api_request",
                return_value={"language": "English"},  # no 'dubbed'
            ),
            self.assertRaises(ValueError) as cm,
        ):
            mydublist.fetch_dataset(confidence="high", force_refresh=True)

        self.assertIn("schema drift", str(cm.exception))
        self.assertIsNone(cache.get("mydublist_dataset_high"))


class GetLocalesTests(SimpleTestCase):
    """Test get_locales match-by-mal-id (uses the real, un-stubbed function)."""

    def test_hit_returns_codes(self):
        """A covered id returns its locale codes."""
        with patch(
            "app.providers.mydublist.fetch_dataset",
            return_value={"1": ["ja-JP", "en-US"]},
        ):
            self.assertEqual(real_get_locales("1"), ["ja-JP", "en-US"])

    def test_int_media_id_is_coerced_to_str(self):
        """An int MAL id matches the str-keyed dataset."""
        with patch(
            "app.providers.mydublist.fetch_dataset",
            return_value={"1": ["ja-JP"]},
        ):
            self.assertEqual(real_get_locales(1), ["ja-JP"])

    def test_miss_returns_none(self):
        """An uncovered id returns None (distinct from [], honours never-blank)."""
        with patch("app.providers.mydublist.fetch_dataset", return_value={}):
            self.assertIsNone(real_get_locales("999"))
