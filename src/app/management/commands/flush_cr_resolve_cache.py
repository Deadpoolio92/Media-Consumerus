"""One-time flush of the Crunchyroll resolution cache (``cr:resolve:*`` keys).

There was a bug where a **Jikan outage was cached as a month-long unresolvable miss**:
:func:`crunchyroll.resolve._jikan_search` returned ``[]`` for both "no results" and
"network error", so during the 2026-08-24 outage roughly 42 titles got cached as
unresolvable for 30 days. The durable fix (in ``resolve.py``) stops new outages from
being cached, but the **already-poisoned keys are still in Redis and will keep serving
stale misses until they expire**.

Run this **once** after deploying the fix to evict every ``cr:resolve:*`` key so the
next "Sync Crunchyroll" beat re-resolves those titles against a live Jikan::

    python manage.py flush_cr_resolve_cache

Use ``--dry-run`` to only report how many keys would be removed without touching them.
"""

from django.core.cache import cache
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    """Delete every ``cr:resolve:*`` cache key (run once post-fix deploy)."""

    help = (
        "Remove all cached Crunchyroll title/code resolutions (cr:resolve:*), "
        "so outage-poisoned misses are re-resolved on the next sync."
    )

    def add_arguments(self, parser):
        """Add the ``--dry-run`` flag."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many keys would be removed without deleting anything.",
        )

    def handle(self, *args, **options):  # noqa: ARG002
        """Flush every ``cr:resolve:*`` cache key (or report them under --dry-run)."""
        dry_run = options["dry_run"]

        pattern = "cr:resolve:*"
        if not hasattr(cache, "delete_pattern"):
            # Non-Redis backend (unlikely here): clear() is the only safe broad move,
            # but the CR cache is not the whole cache, so refuse rather than nuke all.
            self.stderr.write(
                self.style.ERROR(
                    "The configured cache backend has no delete_pattern(); refusing to "
                    "clear the whole cache here. Run this on the Redis-backed deploy "
                    "(docker compose exec app python manage.py flush_cr_resolve_cache)."
                ),
            )
            return

        if dry_run:
            # delete_pattern actually deletes, so for a dry-run we only sample keys and
            # never mutate; the live delete (with count) happens in the normal path.
            sample = self._sample_keys(pattern)
            if sample:
                self.stdout.write(
                    f"DRY RUN: would remove {len(sample)}+ cr:resolve:* key(s), "
                    f"e.g. {', '.join(sample[:5])}"
                )
            else:
                self.stdout.write(
                    "DRY RUN: no cr:resolve:* keys found (cache already clean)."
                )
            return

        count = cache.delete_pattern(pattern, itersize=1000)
        self.stdout.write(
            self.style.SUCCESS(
                f"Flushed {count} cr:resolve:* cache key(s). The next Sync Crunchyroll "
                "beat will re-resolve those titles against a live Jikan."
            ),
        )

    def _sample_keys(self, pattern):
        """Return a small list of matching raw key names for the dry-run report."""
        raw = getattr(cache, "client", None)
        if not raw:
            return []
        try:
            # django_redis exposes a Redis client via cache.client.get_client();
            # grab one and scan for the (already version-pre-prefixed) pattern.
            client = raw.get_client()
            keys = list(client.scan_iter(match=pattern, count=1000))
            # Report only up to the first few for the operator's eyeball.
            return keys[:5]
        except Exception:  # noqa: BLE001 — reporting is best-effort; never crash
            return []
