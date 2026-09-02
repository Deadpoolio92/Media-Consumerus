"""Tests for the CR<->MAL seed map (E9a) + the CR->MAL resolver (E9b)."""

from unittest.mock import patch

import requests
from django.core.cache import cache
from django.test import SimpleTestCase

from integrations.crunchyroll import resolve


class SeedMapTests(SimpleTestCase):
    """The shipped cr_mal_map.json seed."""

    def test_seed_loads_with_expected_size(self):
        """307 pairs (299 high + 5 medium + 3 override; low excluded)."""
        seed = resolve.load_cr_mal_map()
        self.assertEqual(len(seed), 307)

    def test_values_are_str_mal_ids(self):
        """Codes and MAL ids are strings (Item.media_id is a CharField)."""
        seed = resolve.load_cr_mal_map()
        code, mal_id = next(iter(seed.items()))
        self.assertIsInstance(code, str)
        self.assertIsInstance(mal_id, str)
        self.assertTrue(mal_id.isdigit())

    def test_inverse_is_one_to_one(self):
        """The MAL->code inverse covers every pair (seed is 1:1)."""
        seed = resolve.load_cr_mal_map()
        inverse = resolve.mal_to_cr()
        self.assertEqual(len(inverse), len(seed))
        # round-trips: known seed entry resolves back to its code
        code, mal_id = next(iter(seed.items()))
        self.assertEqual(inverse[mal_id], code)

    def test_known_override_entry_present(self):
        """A sanity-pin on a known seed pair (Witch Hat Atelier -> MAL 51553)."""
        self.assertEqual(resolve.load_cr_mal_map().get("GT00258001"), "51553")


class SeriesUrlTests(SimpleTestCase):
    """series_url() — the E6 CR deep-link builder over the seed map."""

    def test_seed_hit_builds_series_url(self):
        """A MAL id in the seed yields the /series/{code} web URL."""
        self.assertEqual(
            resolve.series_url("51553"),
            "https://www.crunchyroll.com/series/GT00258001",
        )

    def test_accepts_int_mal_id(self):
        """media_id arrives as an int from the provider; it's coerced to str."""
        self.assertEqual(
            resolve.series_url(51553),
            "https://www.crunchyroll.com/series/GT00258001",
        )

    def test_seed_miss_returns_none(self):
        """An id absent from the seed yields None (no guessing a code)."""
        self.assertIsNone(resolve.series_url("999999999"))


class NormalizeTests(SimpleTestCase):
    """The shared title normalizer (ported from E10)."""

    def test_strips_accents_articles_punctuation(self):
        """Accents/articles/punctuation/case fold to a comparable form."""
        self.assertEqual(resolve.normalize("The Café—Déjà Vu!"), "cafe deja vu")

    def test_ampersand_becomes_and(self):
        """'&' is spelled out so 'Fruits & Veg' matches 'Fruits and Veg'."""
        self.assertEqual(resolve.normalize("Fruits & Veg"), "fruits and veg")


class ResolveTitleToMalTests(SimpleTestCase):
    """Exact-only Jikan fallback (skip-don't-guess)."""

    def setUp(self):
        """Isolate the resolution cache per test."""
        cache.clear()  # resolutions are cached; isolate each test

    def test_exact_normalized_match_wins(self):
        """A candidate whose normalized title equals the query resolves."""
        candidates = [
            {"mal_id": "999", "titles": ["Totally Different"]},
            {"mal_id": "123", "titles": ["Frieren: Beyond Journeys End"]},
        ]
        with patch.object(resolve, "_jikan_search", return_value=candidates):
            self.assertEqual(
                resolve.resolve_title_to_mal("Frieren - Beyond Journeys End"),
                "123",
            )

    def test_fuzzy_near_miss_is_skipped(self):
        """A close-but-not-exact candidate yields None (never guess a write target)."""
        candidates = [{"mal_id": "500", "titles": ["Attack on Titan Final Season"]}]
        with patch.object(resolve, "_jikan_search", return_value=candidates):
            self.assertIsNone(resolve.resolve_title_to_mal("Attack on Titan"))

    def test_result_is_cached(self):
        """A second call doesn't re-hit Jikan (hit cached by normalized title)."""
        candidates = [{"mal_id": "42", "titles": ["Show X"]}]
        with patch.object(
            resolve,
            "_jikan_search",
            return_value=candidates,
        ) as mock_search:
            resolve.resolve_title_to_mal("Show X")
            resolve.resolve_title_to_mal("show   x")  # same normalized form
        mock_search.assert_called_once()

    def test_miss_is_cached(self):
        """An unresolved title is cached as a miss (no repeat Jikan calls)."""
        with patch.object(
            resolve,
            "_jikan_search",
            return_value=[],
        ) as mock_search:
            self.assertIsNone(resolve.resolve_title_to_mal("Nonexistent"))
            self.assertIsNone(resolve.resolve_title_to_mal("Nonexistent"))
        mock_search.assert_called_once()


class CrCodeToMalTests(SimpleTestCase):
    """Seed-first, then the exact-only Jikan fallback."""

    def setUp(self):
        """Isolate the resolution cache per test."""
        cache.clear()

    def test_seed_hit_skips_jikan(self):
        """A code in the seed resolves without any Jikan call."""
        with patch.object(resolve, "_jikan_search") as mock_search:
            self.assertEqual(resolve.cr_code_to_mal("GT00258001", "Witch Hat"), "51553")
        mock_search.assert_not_called()

    def test_fallback_resolves_new_code(self):
        """A code absent from the seed falls back to title resolution."""
        candidates = [{"mal_id": "777", "titles": ["Brand New Show"]}]
        with patch.object(resolve, "_jikan_search", return_value=candidates):
            self.assertEqual(
                resolve.cr_code_to_mal("GTUNKNOWN", "Brand New Show"),
                "777",
            )

    def test_unresolvable_code_returns_none(self):
        """A new code whose title can't be matched -> None (caller skips)."""
        with patch.object(resolve, "_jikan_search", return_value=[]):
            self.assertIsNone(resolve.cr_code_to_mal("GTNOPE", "Mystery"))


class JikanOutageTests(SimpleTestCase):
    """A Jikan outage must never be cached as a month-long miss (2026-08-24 bug)."""

    def setUp(self):
        """Isolate the resolution cache per test."""
        cache.clear()

    def _outage(self):
        return patch.object(
            resolve,
            "_jikan_search",
            side_effect=resolve.JikanSearchError("offline"),
        )

    def test_title_outage_propagates_and_is_not_cached(self):
        """resolve_title_to_mal raises on outage and stores nothing in the cache."""
        key = "cr:resolve:title:show q"
        with self._outage(), self.assertRaises(resolve.JikanSearchError):
            resolve.resolve_title_to_mal("Show Q")
        # The failed fetch must not leave a cached miss behind.
        self.assertIsNone(cache.get(key))
        # Once Jikan is back the re-hit actually resolves -> nothing was poisoned.
        candidates = [{"mal_id": "88", "titles": ["Show Q"]}]
        with patch.object(
            resolve, "_jikan_search", return_value=candidates
        ) as mock_search:
            self.assertEqual(resolve.resolve_title_to_mal("Show Q"), "88")
        mock_search.assert_called_once()

    def test_code_outage_returns_none_without_caching(self):
        """cr_code_to_mal returns None on an outage but leaves the code key empty."""
        key = "cr:resolve:code:GTXOFFLINE"
        with self._outage():
            self.assertIsNone(resolve.cr_code_to_mal("GTXOFFLINE", "Show Q"))
        self.assertIsNone(cache.get(key))
        # The next beat re-hits Jikan instead of reading a stale miss.
        candidates = [{"mal_id": "88", "titles": ["Show Q"]}]
        with patch.object(
            resolve, "_jikan_search", return_value=candidates
        ) as mock_search:
            self.assertEqual(resolve.cr_code_to_mal("GTXOFFLINE", "Show Q"), "88")
        mock_search.assert_called_once()

    def test_genuine_miss_is_still_cached(self):
        """A successful empty search (real miss) is cached; only outages aren't."""
        key = "cr:resolve:title:neverseen"
        with patch.object(resolve, "_jikan_search", return_value=[]) as miss_search:
            self.assertIsNone(resolve.resolve_title_to_mal("NeverSeen"))
            self.assertIsNone(resolve.resolve_title_to_mal("NeverSeen"))
        miss_search.assert_called_once()  # miss cached -> no repeat Jikan call
        self.assertEqual(cache.get(key), resolve._MISS)


def _resp(status, payload=None, retry_after=None):
    """Build a requests.Response with a configurable status/payload/header."""
    r = requests.Response()
    r.status_code = status
    r.headers["Retry-After"] = retry_after or ""
    r.json = lambda: payload if payload is not None else {}
    return r


def _ok_resp(mal_id="123", title="Foo"):
    """Build a 200 search response containing one candidate."""
    payload = {
        "data": [
            {
                "mal_id": mal_id,
                "title": title,
                "title_english": None,
                "title_japanese": None,
                "titles": [],
            }
        ],
    }
    return _resp(200, payload=payload)


class JikanRetryHelperTests(SimpleTestCase):
    """_retryable / _retry_delay — transient vs fatal + capped backoff."""

    def test_retryable_classification(self):
        """Network errors, 429, and 5xx are transient; 4xx/200 are not."""
        self.assertTrue(resolve._retryable(None))  # no HTTP response
        self.assertTrue(resolve._retryable(429))
        self.assertTrue(resolve._retryable(500))
        self.assertTrue(resolve._retryable(503))
        self.assertFalse(resolve._retryable(200))
        self.assertFalse(resolve._retryable(400))
        self.assertFalse(resolve._retryable(404))

    def test_retry_delay_honors_retry_after_and_caps(self):
        """Retry-After is used; huge values and backoff are capped at JIKAN_MAX_WAIT."""
        self.assertEqual(resolve._retry_delay(_resp(429, retry_after="2"), 1), 2.0)
        big = _resp(429, retry_after="999")
        self.assertEqual(resolve._retry_delay(big, 1), resolve.JIKAN_MAX_WAIT)
        self.assertEqual(
            resolve._retry_delay(None, 9),
            resolve.JIKAN_MAX_WAIT,  # backoff capped
        )
        self.assertLess(
            resolve._retry_delay(None, 1),
            resolve._retry_delay(None, 3),
        )  # grows with attempt


class JikanRetrySearchTests(SimpleTestCase):
    """_jikan_search retries transient 429/5xx/network errors before giving up."""

    @staticmethod
    def _sleepless():
        return patch.object(resolve.time, "sleep")

    def test_retries_on_429_then_succeeds(self):
        """A rate-limited first hit is retried (honouring Retry-After) and resolves."""
        with (
            patch.object(
                resolve.requests,
                "get",
                side_effect=[_resp(429, retry_after="2"), _ok_resp()],
            ) as mock_get,
            self._sleepless(),
        ):
            cands = resolve._jikan_search("Foo")
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(cands[0]["mal_id"], "123")

    def test_retries_on_5xx_then_succeeds(self):
        """A 504 gateway blip is retried and the title still resolves."""
        with (
            patch.object(
                resolve.requests,
                "get",
                side_effect=[_resp(504), _ok_resp()],
            ) as mock_get,
            self._sleepless(),
        ):
            cands = resolve._jikan_search("Foo")
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(cands[0]["mal_id"], "123")

    def test_retries_on_connection_error_then_succeeds(self):
        """A transient connection failure is retried."""
        with (
            patch.object(
                resolve.requests,
                "get",
                side_effect=[requests.exceptions.ConnectionError, _ok_resp()],
            ) as mock_get,
            self._sleepless(),
        ):
            cands = resolve._jikan_search("Foo")
        self.assertEqual(mock_get.call_count, 2)
        self.assertEqual(len(cands), 1)

    def test_exhausted_retries_raise(self):
        """Persistent 429/5xx across all attempts raise JikanSearchError (no hang)."""
        for status in (429, 503, 504):
            with (
                patch.object(
                    resolve.requests,
                    "get",
                    return_value=_resp(status),
                ) as mock_get,
                patch.object(resolve.time, "sleep"),
                self.assertRaises(resolve.JikanSearchError),
            ):
                resolve._jikan_search("Foo")
            # Every attempt is spent; failure is counted (uncached by callers).
            self.assertEqual(mock_get.call_count, resolve.JIKAN_MAX_ATTEMPTS)

    def test_non_transient_4xx_fails_immediately(self):
        """A 400 is fatal on the first request, not hammered with retries."""
        with (
            patch.object(
                resolve.requests,
                "get",
                return_value=_resp(400),
            ) as mock_get,
            patch.object(resolve.time, "sleep"),
            self.assertRaises(resolve.JikanSearchError),
        ):
            resolve._jikan_search("Foo")
        mock_get.assert_called_once()


class JikanThrottleTests(SimpleTestCase):
    """The global per-second limiter is invoked on every Jikan search."""

    def test_search_invokes_global_throttle(self):
        """_jikan_search goes through _jikan_throttle before each request."""
        with (
            patch.object(resolve, "_jikan_throttle") as mock_throttle,
            patch.object(resolve.requests, "get", return_value=_ok_resp()),
        ):
            resolve._jikan_search("Foo")
        mock_throttle.assert_called_once()


class GenericSeasonLabelTests(SimpleTestCase):
    """_is_generic_season_label — CR's generic season labels vs real titles."""

    def test_recognizes_generic_labels(self):
        """Pure 'Season N' / OVA / Special / Movie labels are generic."""
        for label in (
            "Season 2",
            "Season 10",
            "OVAs",
            "OVA",
            "Specials",
            "Special",
            "Movies",
            "Movie",
        ):
            self.assertTrue(
                resolve._is_generic_season_label(resolve.normalize(label)),
                label,
            )

    def test_ignores_real_titles(self):
        """A real title that merely contains 'Season N' is not generic."""
        for label in (
            "Attack on Titan Season 2",
            "Season 2: Part 2",
            "Frieren",
        ):
            self.assertFalse(
                resolve._is_generic_season_label(resolve.normalize(label)),
                label,
            )


class GenericSeasonSkipTests(SimpleTestCase):
    """resolve_title_to_mal skips generic labels without hitting Jikan."""

    def setUp(self):
        """Isolate the resolution cache per test."""
        cache.clear()

    def test_generic_label_skips_jikan_and_caches_miss(self):
        """'Season 2' never queries Jikan and is cached as a deterministic miss."""
        with patch.object(resolve, "_jikan_search") as mock_search:
            self.assertIsNone(resolve.resolve_title_to_mal("Season 2"))
            self.assertIsNone(resolve.resolve_title_to_mal("Season 2"))
        mock_search.assert_not_called()
        self.assertEqual(cache.get("cr:resolve:title:season 2"), resolve._MISS)

    def test_real_title_still_queries_jikan(self):
        """A real title containing 'Season 2' still resolves via Jikan."""
        candidates = [{"mal_id": "1", "titles": ["Attack on Titan Season 2"]}]
        with patch.object(
            resolve,
            "_jikan_search",
            return_value=candidates,
        ) as mock_search:
            self.assertEqual(
                resolve.resolve_title_to_mal("Attack on Titan Season 2"),
                "1",
            )
        mock_search.assert_called_once()
