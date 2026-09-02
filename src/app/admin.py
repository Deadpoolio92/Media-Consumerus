import contextlib

from django.apps import apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered

from app.models import (
    AnimeAvailability,
    CrunchyrollCredential,
    Episode,
    Item,
    ItemMetadata,
    StreamingLink,
    UserMessage,
)


# Custom ModelAdmin classes with search functionality
@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    """Custom admin for Item model with search and filter options."""

    search_fields = ["title", "media_id", "source"]
    list_display = [
        "title",
        "media_id",
        "season_number",
        "episode_number",
        "media_type",
        "source",
    ]
    list_filter = ["media_type", "source"]


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    """Custom admin for Episode model with search and filter options."""

    search_fields = ["item__title", "related_season__item__title"]
    list_display = ["__str__", "end_date"]


@admin.register(UserMessage)
class UserMessageAdmin(admin.ModelAdmin):
    """Custom admin for persistent user messages."""

    search_fields = ["user__username", "message"]
    list_display = ["message", "level", "user", "created_at", "shown_at"]
    list_filter = ["level", "shown_at"]


@admin.register(AnimeAvailability)
class AnimeAvailabilityAdmin(admin.ModelAdmin):
    """Custom admin for title-level anime dub/sub availability.

    Explicit so it isn't swept into ``MediaAdmin`` (which expects
    status/score/user fields this model doesn't have).
    """

    search_fields = ["item__title"]
    list_display = ["__str__", "source", "updated_at"]
    list_filter = ["source"]
    list_select_related = ["item"]


@admin.register(ItemMetadata)
class ItemMetadataAdmin(admin.ModelAdmin):
    """Custom admin for denormalized catalog facts (genre + year).

    Explicit so it isn't swept into ``MediaAdmin`` (which expects
    status/score/user fields this model doesn't have).
    """

    search_fields = ["item__title"]
    list_display = ["__str__", "release_year", "updated_at"]
    list_filter = ["release_year"]
    list_select_related = ["item"]


@admin.register(StreamingLink)
class StreamingLinkAdmin(admin.ModelAdmin):
    """Custom admin for user-added streaming links (E6).

    Explicit so it isn't swept into ``MediaAdmin`` (which expects
    status/score/user fields this model doesn't have).
    """

    search_fields = ["item__title", "name", "url"]
    list_display = ["name", "item", "url", "created_at"]
    list_select_related = ["item"]


@admin.register(CrunchyrollCredential)
class CrunchyrollCredentialAdmin(admin.ModelAdmin):
    """Admin for the CR etp_rt store (E9.5) — read-mostly.

    Explicit so it isn't swept into ``MediaAdmin`` (which expects item/user fields
    and read-only status/score logic). The value is shown decrypted for recovery
    convenience.
    """

    list_display = ["updated_at"]
    readonly_fields = ["etp_rt", "etp_rt_vid", "updated_at"]


class MediaAdmin(admin.ModelAdmin):
    """Custom admin for regular media model with search and filter options."""

    search_fields = ["item__title", "user__username", "notes"]
    list_display = ["__str__", "status", "score", "user"]
    list_filter = ["status"]


# Register models with custom admin classes


# Auto-register remaining models
app_models = apps.get_app_config("app").get_models()
SpecialModels = [
    "Item",
    "Episode",
    "BasicMedia",
    "UserMessage",
    "AnimeAvailability",
    "ItemMetadata",
    "StreamingLink",
    "CrunchyrollCredential",
]
for model in app_models:
    if (
        not model.__name__.startswith("Historical")
        and model.__name__ not in SpecialModels
    ):
        with contextlib.suppress(AlreadyRegistered):
            admin.site.register(model, MediaAdmin)
