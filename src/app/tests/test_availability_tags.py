from django.test import SimpleTestCase

from app.templatetags.availability_tags import locale_display


class LocaleDisplayFilterTests(SimpleTestCase):
    """Test the locale_display template filter."""

    def test_known_code_renders_display_name(self):
        """A known locale code renders its English display name."""
        self.assertEqual(locale_display("en-US"), "English")

    def test_unknown_code_passes_through_unchanged(self):
        """An unmapped code is shown raw rather than dropped or erroring."""
        self.assertEqual(locale_display("zz-ZZ"), "zz-ZZ")
