"""Tests for the CR<->MAL seed map (E9a) + the CR->MAL resolver (E9b)."""

from unittest.mock import patch

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
