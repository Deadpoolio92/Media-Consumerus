"""One-off Crunchyroll dub/sub backfill into ``AnimeAvailability`` (E9a / C1).

Mints a short-lived CR access token from the stored ``etp_rt`` cookie, fetches the CR
catalog once, and fills audio + subtitle locales for every tracked MAL anime (library-
only; never adds items). Re-runnable and idempotent — only changed rows are written and
a title CR has no data for is never blanked.

This is a foreground command (not a Celery beat): availability changes slowly, E1's
MyDubList beat keeps audio fresh, and a command keeps the unofficial-API surface to an
on-demand run (eng-review decision D8). The recurring CR beat arrives with E9b.

Requires ``CRUNCHYROLL_ETP_RT`` and ``CRUNCHYROLL_BASIC_AUTH`` (env/override). See the
E9 runbook for how to capture both from a logged-in browser.

Usage::

    python manage.py backfill_crunchyroll_availability
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from integrations.crunchyroll import client, sync


class Command(BaseCommand):
    """Backfill anime dub/sub availability from Crunchyroll (one-off)."""

    help = "Backfill anime dub/sub availability from the Crunchyroll catalog (C1)."

    def handle(self, *args, **options):  # noqa: ARG002
        """Mint a token, run the C1 backfill, and print a summary."""
        etp_rt = getattr(settings, "CRUNCHYROLL_ETP_RT", "")
        if not etp_rt:
            msg = (
                "CRUNCHYROLL_ETP_RT is not set. Copy the 'etp_rt' cookie from a "
                "logged-in browser into the env/override (see the E9 runbook)."
            )
            raise CommandError(msg)

        self.stdout.write("Minting Crunchyroll token…")
        try:
            token = client.mint_token(etp_rt)
        except (ValueError, OSError) as exc:
            # OSError covers requests' network/HTTP errors (RequestException subclass).
            msg = f"Crunchyroll auth failed: {exc}"
            raise CommandError(msg) from exc

        self.stdout.write("Fetching catalog and backfilling availability…")
        counts = sync.backfill_c1(token)

        self.stdout.write(
            self.style.SUCCESS(
                "Crunchyroll C1 backfill complete: "
                f"{counts['written']} written, {counts['unchanged']} unchanged, "
                f"{counts['unmatched']} unmatched, {counts['errors']} errors "
                f"(of {counts['library']} library anime).",
            ),
        )
        self.stdout.write(
            "  matched via: "
            f"seed={counts['via_seed']}, title={counts['via_title']}, "
            f"cms-series={counts['via_series']}",
        )
