"""Backfill stored ``Item`` titles with MAL's English titles.

The MAL provider now prefers ``alternative_titles.en`` over the romaji/native
canonical title (see :func:`app.providers.mal.get_title`), but titles already
stored on ``Item`` were captured before that change. This one-shot command
re-fetches the preferred title for every MAL anime/manga ``Item`` and updates it
in place. Re-runnable and idempotent (only changed titles are written).

Fork enhancement (additive management command — no upstream core file is edited).

Usage::

    python manage.py backfill_mal_titles            # apply changes
    python manage.py backfill_mal_titles --dry-run  # preview only
"""

import time

from django.conf import settings
from django.core.management.base import BaseCommand

from app.models import Item, MediaTypes, Sources
from app.providers import mal, services


class Command(BaseCommand):
    """Re-fetch MAL anime/manga ``Item`` titles, preferring English titles."""

    help = "Re-fetch MAL anime/manga Item titles, preferring English titles."

    def add_arguments(self, parser):
        """Register command-line options."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without writing anything.",
        )
        parser.add_argument(
            "--sleep",
            type=float,
            default=0.3,
            help="Seconds to wait between MAL API calls (rate-limit friendly).",
        )

    def handle(self, *args, **options):  # noqa: ARG002
        """Iterate MAL items, fetch the preferred title, and update changes."""
        dry_run = options["dry_run"]
        sleep = options["sleep"]

        items = Item.objects.filter(
            source=Sources.MAL.value,
            media_type__in=[MediaTypes.ANIME.value, MediaTypes.MANGA.value],
        ).order_by("title")

        total = items.count()
        self.stdout.write(f"Checking {total} MAL item(s)...")

        to_update = []
        failed = 0
        for item in items:
            url = f"{mal.base_url}/{item.media_type}/{item.media_id}"
            try:
                response = services.api_request(
                    Sources.MAL.value,
                    "GET",
                    url,
                    params={"fields": "title,alternative_titles"},
                    headers={"X-MAL-CLIENT-ID": settings.MAL_API},
                )
            except Exception as exc:  # noqa: BLE001 - report and keep going
                failed += 1
                self.stderr.write(f"  ! {item.media_id} {item.title}: {exc}")
                continue

            new_title = mal.get_title(response)
            if new_title and new_title != item.title:
                self.stdout.write(f"  {item.title}  ->  {new_title}")
                item.title = new_title
                to_update.append(item)

            time.sleep(sleep)

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"DRY RUN: {len(to_update)} title(s) would change, "
                    f"{failed} failed, {total} checked.",
                ),
            )
            return

        if to_update:
            # bulk_update bypasses save()/signals - fine for a title-only change
            # and avoids triggering calendar reloads per row.
            Item.objects.bulk_update(to_update, ["title"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Updated {len(to_update)} title(s); {failed} failed; "
                f"{total} checked.",
            ),
        )
