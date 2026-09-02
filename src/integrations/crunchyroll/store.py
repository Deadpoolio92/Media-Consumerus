"""Durable storage for the Crunchyroll ``etp_rt`` cookie (E9.5).

``etp_rt`` used to live only in env (``CRUNCHYROLL_ETP_RT``), which is immutable at
runtime — so a *rotated* cookie (from :func:`client.account_login`) had nowhere to land.
These helpers keep a single ``app.CrunchyrollCredential`` row as the writable store:

  * :func:`resolve_etp_rt` — return the effective cookie. Seeds the row from the env
    value once (so existing deployments adopt this without re-capturing), then the DB
    value is authoritative.
  * :func:`set_etp_rt` — overwrite the stored cookie (auto-renewal writes a fresh
    ``etp_rt`` here after a successful login).

Values are stored **encrypted** via ``integrations.imports.helpers.encrypt`` (Fernet
keyed off ``SECRET_KEY``), the same pattern Trakt/SIMKL use for refresh tokens. This
module is the only place the ``CrunchyrollCredential`` model is touched.
"""

from django.conf import settings

from app.models import CrunchyrollCredential
from integrations.imports import helpers

# The singleton row's fixed pk (one credential, no custom constraint needed).
CR_SINGLETON_PK = 1


def resolve_etp_rt():
    """Return the effective CR ``etp_rt`` (DB, env-seeded once), or ``""`` if unset.

    A first caller with an env ``CRUNCHYROLL_ETP_RT`` migrates it into the
    ``CrunchyrollCredential`` row (encrypted) and returns it; subsequent callers read
    the (possibly rotated) DB value. Returns ``""`` when neither source has a cookie.
    """
    row = CrunchyrollCredential.objects.filter(pk=CR_SINGLETON_PK).first()
    if row is None:
        env_val = getattr(settings, "CRUNCHYROLL_ETP_RT", "")
        if not env_val:
            return ""
        row = CrunchyrollCredential.objects.create(
            pk=CR_SINGLETON_PK, etp_rt=helpers.encrypt(env_val),
        )
    if not row.etp_rt:
        return ""
    return helpers.decrypt(row.etp_rt)


def set_etp_rt(etp_rt, etp_rt_vid=None):
    """Overwrite the stored cookie (encrypted), created on demand.

    Called after a successful :func:`client.account_login` so the next sync uses the
    freshly-rotated ``etp_rt``. ``etp_rt_vid`` (the companion cookie, when the server
    returns one) is stored the same way.
    """
    row, _ = CrunchyrollCredential.objects.get_or_create(pk=CR_SINGLETON_PK)
    row.etp_rt = helpers.encrypt(etp_rt)
    row.etp_rt_vid = helpers.encrypt(etp_rt_vid) if etp_rt_vid else ""
    row.save(update_fields=["etp_rt", "etp_rt_vid", "updated_at"])
    return row
