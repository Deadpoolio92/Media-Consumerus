from django.test import SimpleTestCase

from app.models import AvailabilitySource
from app.providers import mydublist
from app.templatetags.availability_tags import locale_display, mydublist_credit


class LocaleDisplayFilterTests(SimpleTestCase):
    """Test the locale_display template filter."""

    def test_known_code_renders_display_name(self):
        """A known locale code renders its English display name."""
        self.assertEqual(locale_display("en-US"), "English")

    def test_unknown_code_passes_through_unchanged(self):
        """An unmapped code is shown raw rather than dropped or erroring."""
        self.assertEqual(locale_display("zz-ZZ"), "zz-ZZ")


class MyDubListCreditTagTests(SimpleTestCase):
    """Test the mydublist_credit attribution tag (CC BY 4.0 compliance)."""

    def test_mydublist_source_returns_attribution(self):
        """MyDubList-sourced rows surface the required credit line."""
        self.assertEqual(
            mydublist_credit(AvailabilitySource.MYDUBLIST.value),
            mydublist.ATTRIBUTION,
        )

    def test_manual_source_returns_empty(self):
        """Manual rows need no MyDubList attribution."""
        self.assertEqual(mydublist_credit(AvailabilitySource.MANUAL.value), "")

    def test_crunchyroll_source_returns_empty(self):
        """Other auto sources need no MyDubList attribution."""
        self.assertEqual(mydublist_credit(AvailabilitySource.CRUNCHYROLL.value), "")
