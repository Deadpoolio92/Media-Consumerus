"""List the shared Crunchyroll account's profiles (E9 setup helper).

Mints a token from ``CRUNCHYROLL_ETP_RT`` and prints each profile's id / name /
primary / selected flags, so the maintainer can pick their own and set
``CRUNCHYROLL_PROFILE_ID`` ahead of E9b (watchlist/history sync is per-profile on a
shared account). E9a's dub/sub backfill is profile-independent, so this is purely
forward-setup + an early verification that the token + multiprofile endpoint work.

The profile **switch** mechanism (binding a minted token to a chosen profile) is the
unofficial bit verified/used in E9b; this command only *reads* the profile list.

Usage::

    python manage.py list_crunchyroll_profiles
"""

from django.core.management.base import BaseCommand, CommandError

from integrations import tasks
from integrations.crunchyroll import client, store


class Command(BaseCommand):
    """Print the CR account's profiles (id / name / primary / selected)."""

    help = "List the shared Crunchyroll account's profiles for CRUNCHYROLL_PROFILE_ID."

    def handle(self, *args, **options):  # noqa: ARG002
        """Mint a token and print the profile list."""
        etp_rt = store.resolve_etp_rt()
        if not etp_rt:
            msg = "CRUNCHYROLL_ETP_RT is not set (see the E9 runbook)."
            raise CommandError(msg)

        try:
            token = tasks.mint_with_renewal(etp_rt)
            profiles = client.list_profiles(token)
        except (ValueError, OSError) as exc:
            msg = f"Crunchyroll request failed: {exc}"
            raise CommandError(msg) from exc

        if not profiles:
            self.stdout.write(self.style.WARNING("No profiles returned."))
            return

        self.stdout.write(f"Found {len(profiles)} profile(s):")
        for p in profiles:
            flags = []
            if p.get("is_primary"):
                flags.append("primary")
            if p.get("is_selected"):
                flags.append("selected")
            suffix = f"  [{', '.join(flags)}]" if flags else ""
            self.stdout.write(
                f"  {p.get('profile_name', '?')} — "
                f"profile_id={p.get('profile_id', '?')}{suffix}",
            )
        self.stdout.write(
            "\nSet CRUNCHYROLL_PROFILE_ID to your own profile_id (used by E9b C2/C3).",
        )
