from django.test import SimpleTestCase

from app import languages


class DisplayNameTests(SimpleTestCase):
    """Test languages.display_name (code -> display name)."""

    def test_known_code_returns_display_name(self):
        """A known code resolves to its English display name."""
        self.assertEqual(languages.display_name("ja-JP"), "Japanese")

    def test_unknown_code_passes_through_unchanged(self):
        """An unmapped code is shown raw, not swallowed or errored."""
        self.assertEqual(languages.display_name("xx-XX"), "xx-XX")


class CodeForDisplayTests(SimpleTestCase):
    """Test languages.code_for_display (display name/code -> canonical code)."""

    def test_known_display_name_resolves_case_insensitively(self):
        """A display name resolves regardless of case."""
        self.assertEqual(languages.code_for_display("japanese"), "ja-JP")
        self.assertEqual(languages.code_for_display("JAPANESE"), "ja-JP")

    def test_known_code_passed_in_resolves_to_itself(self):
        """Passing an already-canonical code resolves to that same code."""
        self.assertEqual(languages.code_for_display("es-419"), "es-419")

    def test_whitespace_is_trimmed(self):
        """Leading/trailing whitespace around a display name is trimmed."""
        self.assertEqual(languages.code_for_display("  Japanese  "), "ja-JP")

    def test_unknown_text_returns_none(self):
        """Text matching neither a code nor a display name returns None."""
        self.assertIsNone(languages.code_for_display("Klingon"))

    def test_disambiguates_regional_variants(self):
        """Spanish (Latin America) and Spanish (Spain) resolve distinctly."""
        self.assertEqual(
            languages.code_for_display("Spanish (Latin America)"),
            "es-419",
        )
        self.assertEqual(languages.code_for_display("Spanish (Spain)"), "es-ES")

    def test_known_code_resolves_regardless_of_case(self):
        """A known code typed in the wrong case still resolves (regression)."""
        self.assertEqual(languages.code_for_display("JA-JP"), "ja-JP")
        self.assertEqual(languages.code_for_display("Ja-Jp"), "ja-JP")
