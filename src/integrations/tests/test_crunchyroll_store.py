"""Tests for the E9.5 CrunchyrollCredential store (encrypted DB etp_rt).

The store is the writable home for the rotating ``etp_rt`` cookie: it seeds once from
env then serves/rewrites the DB value, encrypting at rest (Fernet off SECRET_KEY).
"""

from django.test import TestCase, override_settings

from app.models import CrunchyrollCredential
from integrations.crunchyroll import store
from integrations.imports import helpers


class ResolveEtpRtTests(TestCase):
    """resolve_etp_rt — env-seed-once + DB-authoritative reads."""

    @override_settings(CRUNCHYROLL_ETP_RT="")
    def test_returns_empty_when_unset(self):
        """Neither env nor a stored row -> empty string (sync skips)."""
        self.assertEqual(store.resolve_etp_rt(), "")

    @override_settings(CRUNCHYROLL_ETP_RT="")
    def test_empty_env_leaves_no_row(self):
        """No env value means no credential row is created."""
        store.resolve_etp_rt()
        self.assertFalse(CrunchyrollCredential.objects.exists())

    @override_settings(CRUNCHYROLL_ETP_RT="seed-cookie")
    def test_seeds_from_settings_once(self):
        """First access migrates the env cookie into the DB and returns it."""
        self.assertEqual(store.resolve_etp_rt(), "seed-cookie")
        # The DB value is authoritative now — and stored encrypted, not plaintext.
        row = CrunchyrollCredential.objects.get(pk=store.CR_SINGLETON_PK)
        self.assertNotIn("seed-cookie", row.etp_rt)
        self.assertEqual(helpers.decrypt(row.etp_rt), "seed-cookie")
        # A second read resolves from the DB (no env dependency).
        self.assertEqual(store.resolve_etp_rt(), "seed-cookie")


class SetEtpRtTests(TestCase):
    """set_etp_rt — upsert a rotated cookie (and optional etp_rt_vid)."""

    @override_settings(CRUNCHYROLL_ETP_RT="")
    def test_set_then_resolve_roundtrip(self):
        """A rotated cookie written by renewal is the next sync's cookie."""
        store.set_etp_rt("fresh-cookie", "etp_rt_vid-value")
        self.assertEqual(store.resolve_etp_rt(), "fresh-cookie")
        row = CrunchyrollCredential.objects.get(pk=store.CR_SINGLETON_PK)
        self.assertEqual(helpers.decrypt(row.etp_rt_vid), "etp_rt_vid-value")

    @override_settings(CRUNCHYROLL_ETP_RT="")
    def test_set_without_vid_keeps_vid_empty(self):
        """etp_rt_vid defaults to empty when the server returns none."""
        store.set_etp_rt("fresh-cookie")
        row = CrunchyrollCredential.objects.get(pk=store.CR_SINGLETON_PK)
        self.assertEqual(row.etp_rt_vid, "")

    @override_settings(CRUNCHYROLL_ETP_RT="seed-cookie")
    def test_set_overrides_env_seed(self):
        """A renewal write wins over the env seed."""
        self.assertEqual(store.resolve_etp_rt(), "seed-cookie")  # seed once
        store.set_etp_rt("rotated-cookie")
        self.assertEqual(store.resolve_etp_rt(), "rotated-cookie")
