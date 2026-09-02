"""Manual one-shot of the Crunchyroll watchlist->status + history->progress sync (E9b).

Runs the same logic as the daily "Sync Crunchyroll" beat, but in the foreground with a
printed summary instead of the beat's silent failure-streak signalling — handy for the
first run, for verifying ``CRUNCHYROLL_PROFILE_ID``, or after binge-watching.

Requires ``CRUNCHYROLL_ETP_RT``, ``CRUNCHYROLL_BASIC_AUTH`` and
``CRUNCHYROLL_PROFILE_ID`` (env/override). See the E9 runbook; find your profile id
with ``manage.py list_crunchyroll_profiles``.

Usage::

    python manage.py sync_crunchyroll_status
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from integrations import tasks
from integrations.crunchyroll import store


class Command(BaseCommand):
    """Pull Crunchyroll watchlist->status and history->progress once (foreground)."""

    help = "Sync Crunchyroll watchlist->status and history->progress (C2/C3, one-off)."

    def handle(self, *args, **options):  # noqa: ARG002
        """Resolve the user + token, run C2/C3, and print a summary."""
        etp_rt = store.resolve_etp_rt()
        profile_id = getattr(settings, "CRUNCHYROLL_PROFILE_ID", "")
        if not etp_rt:
            msg = "CRUNCHYROLL_ETP_RT is not set (see the E9 runbook)."
            raise CommandError(msg)
        if not profile_id:
            msg = (
                "CRUNCHYROLL_PROFILE_ID is not set. Run "
                "`manage.py list_crunchyroll_profiles` to find yours and set it "
                "(C2/C3 refuse to write without a confirmed profile)."
            )
            raise CommandError(msg)

        user = tasks.resolve_cr_user()
        if user is None:
            msg = (
                "Could not determine which user to sync. Set CRUNCHYROLL_USERNAME "
                "(more than one user exists)."
            )
            raise CommandError(msg)

        self.stdout.write(f"Syncing Crunchyroll for {user}…")
        try:
            result = tasks.run_crunchyroll_sync(user, etp_rt, profile_id)
        except (ValueError, OSError) as exc:
            # OSError covers requests' network/HTTP errors (RequestException subclass).
            msg = f"Crunchyroll sync failed: {exc}"
            raise CommandError(msg) from exc

        c2, c3 = result["c2"], result["c3"]
        self.stdout.write(
            self.style.SUCCESS(
                "Crunchyroll sync complete.\n"
                f"  C2 watchlist: {c2['planning_created']} new Planning, "
                f"{c2['skipped']} already tracked, {c2['unmatched']} unmatched, "
                f"{c2['errors']} errors (of {c2['watchlist']}).\n"
                f"  C3 history: {c3['written']} written, {c3['unchanged']} unchanged, "
                f"{c3['skipped']} skipped, {c3['unmatched']} unmatched, "
                f"{c3['via_season']} via-season, "
                f"{c3['multi_season_skipped']} multi-season-skipped, "
                f"{c3['errors']} errors (of {c3['series']} series/season keys).",
            ),
        )
