import logging
from datetime import timedelta

import requests
from celery import shared_task
from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from app import metadata_fields
from app.models import (
    AnimeAvailability,
    AvailabilitySource,
    Item,
    ItemMetadata,
    MediaTypes,
    Sources,
    UserMessage,
)
from app.providers import mydublist
from app.providers.services import ProviderAPIError

logger = logging.getLogger(__name__)


@shared_task(name="Cleanup user messages")
def cleanup_user_messages():
    """Delete shown user messages older than the configured retention window."""
    cutoff = timezone.now() - timedelta(days=settings.USER_MESSAGE_RETENTION_DAYS)
    deleted_count, _ = UserMessage.objects.filter(
        shown_at__isnull=False,
        shown_at__lt=cutoff,
    ).delete()

    logger.info("Deleted %s old shown user messages.", deleted_count)

    return deleted_count


def upsert_availability(item, *, audio=None, subtitle=None, source):
    """Upsert one anime's dub/sub availability; return ``True`` if a row was written.

    The single writer shared by every availability source (MyDubList = audio-only,
    Crunchyroll = audio + subtitle). Honours the ``AnimeAvailability`` write rules in
    ONE place so they can't drift between callers:

      * ``audio`` / ``subtitle`` are written only when passed a list; **``None`` means
        "no data for this field — leave it untouched"** (the no-blank rule: an
        uncovered field is never blanked). Callers convert an empty provider result
        to ``None`` rather than passing ``[]``.
      * last-write-wins: a *differing* provided value overwrites the field and sets
        ``source``;
      * identical-value writes are skipped entirely (returns ``False``) so a re-run
        doesn't churn ``updated_at`` or flip a matching entry's source.

    An all-``None`` call is a no-op (returns ``False``).

       caller ──audio/subtitle (list=write, None=skip)──► upsert_availability
                                                              │
                          ┌───────────────── no row? ─────────┤
                          ▼                                   ▼ row exists
                 create(provided fields,             diff provided fields;
                   source); race→fall through        unchanged → return False;
                          │                           else set changed + source,
                          ▼                           save(update_fields)
                     return True                           return True
    """
    if audio is None and subtitle is None:
        return False

    availability = AnimeAvailability.objects.filter(item=item).first()
    if availability is None:
        create_kwargs = {"item": item, "source": source}
        if audio is not None:
            create_kwargs["audio_locales"] = audio
        if subtitle is not None:
            create_kwargs["subtitle_locales"] = subtitle
        try:
            AnimeAvailability.objects.create(**create_kwargs)
        except IntegrityError:
            # Lost a create race against another worker (on-add fetch vs. daily
            # sync hitting the same item) — the OneToOneField now has a row.
            availability = AnimeAvailability.objects.get(item=item)
        else:
            return True

    update_fields = []
    if audio is not None and availability.audio_locales != audio:
        availability.audio_locales = audio
        update_fields.append("audio_locales")
    if subtitle is not None and availability.subtitle_locales != subtitle:
        availability.subtitle_locales = subtitle
        update_fields.append("subtitle_locales")

    if not update_fields:
        return False  # nothing changed — don't churn updated_at or flip source

    availability.source = source
    availability.save(update_fields=[*update_fields, "source", "updated_at"])
    return True


def apply_mydublist_locales(item, locales):
    """Upsert one anime's dub availability from MyDubList; return ``True`` if written.

    Thin wrapper over :func:`upsert_availability` (audio-only, ``source=mydublist``);
    ``subtitle_locales`` is never touched. ``locales`` must be a non-empty list
    (callers skip ``None`` misses) so an uncovered title is never blanked.
    """
    return upsert_availability(
        item,
        audio=locales,
        source=AvailabilitySource.MYDUBLIST.value,
    )


@shared_task(name="Sync dub availability")
def sync_dub_availability():
    """Daily: refresh anime dub availability from MyDubList (library-bounded).

    Iterates every tracked MAL anime ``Item`` and upserts its ``audio_locales`` from
    the MyDubList dataset. A title MyDubList doesn't cover is skipped (never blanked);
    ``subtitle_locales`` is never written. A dataset-fetch failure aborts cleanly,
    leaving existing availability stale-but-intact (no partial blanking).

    Returns the number of rows written.
    """
    try:
        dataset = mydublist.fetch_dataset(force_refresh=True)
    except (requests.exceptions.RequestException, ValueError):
        logger.exception("MyDubList sync aborted: dataset fetch failed")
        return 0

    anime_items = Item.objects.filter(
        media_type=MediaTypes.ANIME.value,
        source=Sources.MAL.value,
    )
    total = 0
    updated = 0
    for item in anime_items.iterator():
        total += 1
        locales = dataset.get(item.media_id)
        if locales is None:
            continue  # never blank a title MyDubList has no data for
        if apply_mydublist_locales(item, locales):
            updated += 1

    logger.info("MyDubList sync: updated %s of %s anime.", updated, total)
    return updated


@shared_task(name="Fetch one dub availability")
def fetch_one_availability(item_id):
    """Best-effort: populate one anime's dub availability from MyDubList on add.

    Enqueued by the ``post_save(Anime)`` signal. Self-heals a cold cache
    (``get_locales`` downloads + caches the dataset), so availability shows up
    seconds after add instead of waiting for the daily sync. Every failure (item
    gone, network, parse, miss) is logged and swallowed — it MUST NOT raise into /
    block the track-anime flow.

    Returns ``True`` if a row was written, else ``False``.
    """
    item = Item.objects.filter(pk=item_id).first()
    if item is None:
        logger.warning("fetch_one_availability: item %s no longer exists", item_id)
        return False

    try:
        locales = mydublist.get_locales(item.media_id)
    except (requests.exceptions.RequestException, ValueError):
        logger.exception("fetch_one_availability: fetch failed for item %s", item_id)
        return False

    if locales is None:
        return False  # not covered — never blank
    return apply_mydublist_locales(item, locales)


# Catalog facts (genre + year) denormalized into ``ItemMetadata`` so the list
# view can filter on them (E2). Errors anywhere here are best-effort: a missing
# row just means that item is absent from genre/year filters until the next sync.
_METADATA_FETCH_ERRORS = (
    requests.exceptions.RequestException,
    ProviderAPIError,
    ValueError,
    KeyError,
)


def apply_catalog_metadata(item, fields):
    """Upsert one item's denormalized genre + year; return ``True`` if written.

    Idempotent: an identical re-fetch is skipped (returns ``False``) so the daily
    sync doesn't churn ``updated_at``. The ``create`` path guards the OneToOne
    insert race between the on-add signal and the daily sync, mirroring
    ``apply_mydublist_locales``.
    """
    genres = fields["genres"]
    release_year = fields["release_year"]

    metadata = ItemMetadata.objects.filter(item=item).first()
    if metadata is None:
        try:
            ItemMetadata.objects.create(
                item=item,
                genres=genres,
                release_year=release_year,
            )
        except IntegrityError:
            metadata = ItemMetadata.objects.get(item=item)
        else:
            return True
    if metadata.genres == genres and metadata.release_year == release_year:
        return False
    metadata.genres = genres
    metadata.release_year = release_year
    metadata.save(update_fields=["genres", "release_year", "updated_at"])
    return True


@shared_task(name="Sync catalog metadata")
def sync_catalog_metadata():
    """Daily: refresh denormalized genre + year for filterable items (E2).

    Iterates every tracked filterable ``Item`` (movie/tv/season/anime/game) and
    upserts its genre + year from the catalog provider. Doubles as the backfill
    for items added before E2. Per-item fetch failures are logged and skipped so
    one bad title can't abort the run.

    Returns the number of rows written.
    """
    items = Item.objects.filter(
        media_type__in=metadata_fields.FILTERABLE_MEDIA_TYPES,
    )
    total = 0
    updated = 0
    for item in items.iterator():
        total += 1
        try:
            fields = metadata_fields.fetch_for_item(item)
        except _METADATA_FETCH_ERRORS:
            logger.exception("Catalog metadata sync: fetch failed for %s", item)
            continue
        if fields is None:
            continue
        if apply_catalog_metadata(item, fields):
            updated += 1

    logger.info("Catalog metadata sync: updated %s of %s items.", updated, total)
    return updated


@shared_task(name="Fetch one item metadata")
def fetch_one_metadata(item_id):
    """Best-effort: populate one item's genre + year on add (E2).

    Enqueued by the ``post_save`` signal on filterable media models. Reuses the
    metadata the track flow just cached, so genre/year show up in filters right
    after add instead of waiting for the daily sync. Every failure (item gone,
    network, parse, no data) is logged and swallowed — it MUST NOT raise into /
    block the track flow.

    Returns ``True`` if a row was written, else ``False``.
    """
    item = Item.objects.filter(pk=item_id).first()
    if item is None:
        logger.warning("fetch_one_metadata: item %s no longer exists", item_id)
        return False

    try:
        fields = metadata_fields.fetch_for_item(item)
    except _METADATA_FETCH_ERRORS:
        logger.exception("fetch_one_metadata: fetch failed for item %s", item_id)
        return False

    if fields is None:
        return False
    return apply_catalog_metadata(item, fields)
