import logging

from celery import states
from celery.signals import before_task_publish
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_celery_results.models import TaskResult

from app.models import TV, Anime, Game, Movie, Season
from app.tasks import fetch_one_availability, fetch_one_metadata

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Anime)
def enqueue_availability_fetch(sender, instance, created, **kwargs):  # noqa: ARG001
    """Enqueue a best-effort dub-availability fetch when a NEW anime is tracked.

    Only fires on create (not status/score edits). Does NO network I/O itself — it
    just enqueues ``fetch_one_availability`` — so add-anime returns instantly. The
    enqueue is wrapped so a broker hiccup can never break the track-anime flow.
    """
    if not created:
        return
    try:
        fetch_one_availability.delay(instance.item_id)
    except Exception:  # enqueue must never block the track-anime flow
        logger.exception(
            "Could not enqueue availability fetch for item %s",
            instance.item_id,
        )


@receiver(post_save, sender=Movie)
@receiver(post_save, sender=TV)
@receiver(post_save, sender=Season)
@receiver(post_save, sender=Anime)
@receiver(post_save, sender=Game)
def enqueue_metadata_fetch(sender, instance, created, **kwargs):  # noqa: ARG001
    """Enqueue a best-effort genre/year fetch when a filterable item is tracked (E2).

    Fires on create only (not status/score edits). Does NO network I/O itself — it
    just enqueues ``fetch_one_metadata`` — so tracking returns instantly, and the
    item shows up in genre/year filters seconds later. The enqueue is wrapped so a
    broker hiccup can never break the track flow.
    """
    if not created:
        return
    try:
        fetch_one_metadata.delay(instance.item_id)
    except Exception:  # enqueue must never block the track flow
        logger.exception(
            "Could not enqueue metadata fetch for item %s",
            instance.item_id,
        )


@before_task_publish.connect
def create_task_result_on_publish(sender=None, headers=None, body=None, **kwargs):  # noqa: ARG001
    """Create a TaskResult object with PENDING status on task publish.

    https://github.com/celery/django-celery-results/issues/286#issuecomment-1279161047
    """
    if "task" not in headers:
        return

    TaskResult.objects.store_result(
        content_type="application/json",
        content_encoding="utf-8",
        task_id=headers["id"],
        result=None,
        status=states.PENDING,
        task_name=headers["task"],
        task_args=headers.get("argsrepr", ""),
        task_kwargs=headers.get("kwargsrepr", ""),
    )
