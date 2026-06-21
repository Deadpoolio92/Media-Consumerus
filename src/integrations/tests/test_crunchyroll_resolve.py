"""Tests for the CR<->MAL seed map (E9a: static seed only)."""

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
