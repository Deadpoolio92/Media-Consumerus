import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

import events
from app.mixins import disable_fetch_releases
from app.models import MediaTypes, UserMessage, UserMessageLevel
from app.templatetags import app_tags
from integrations.crunchyroll import client, store, sync
from integrations.imports import (
    anilist,
    goodreads,
    helpers,
    hltb,
    imdb,
    kitsu,
    mal,
    simkl,
    steam,
    trakt,
    yamtrack,
)

logger = logging.getLogger(__name__)
ERROR_TITLE = "\n\n\n Couldn't import the following media: \n\n"


def format_media_type_display(count, media_type):
    """Format media type display with proper pluralization."""
    if count == 0:
        return None
    if count == 1:
        return f"{count} {dict(MediaTypes.choices).get(media_type, media_type)}"
    return f"{count} {app_tags.media_type_readable_plural(media_type)}"


def format_import_message(imported_counts, warning_messages=None):
    """Format the import result message based on counts and warnings."""
    parts = [
        format_media_type_display(count, media_type)
        for media_type, count in imported_counts.items()
    ]
    parts = [p for p in parts if p is not None]

    if not parts:
        info_message = "No media was imported."
    else:
        info_message = f"Imported {helpers.join_with_commas_and(parts)}."

    if warning_messages:
        return f"{info_message} {ERROR_TITLE} {warning_messages}"
    return info_message


def import_media(
    importer_func,
    identifier,
    user_id,
    mode,
    oauth_username=None,
    **kwargs,
):
    """Handle the import process for different media services."""
    user = get_user_model().objects.get(id=user_id)

    with disable_fetch_releases():
        if oauth_username is None:
            imported_counts, warnings = importer_func(
                identifier,
                user,
                mode,
                **kwargs,
            )
        else:
            imported_counts, warnings = importer_func(
                identifier,
                user,
                mode,
                username=oauth_username,
                **kwargs,
            )

    events.tasks.reload_calendar.delay()

    return format_import_message(imported_counts, warnings)


@shared_task(name="Import from Trakt")
def import_trakt(
    user_id, mode, token=None, file=None, username=None, redirect_uri=None
):
    """Celery task for importing media data from Trakt.

    Can import using OAuth (token provided), public username, or the contents of
    an export archive downloaded from the Trakt website.
    """
    return import_media(
        trakt.importer,
        token,
        user_id,
        mode,
        username,
        redirect_uri=redirect_uri,
        file=file,
    )


@shared_task(name="Import from SIMKL")
def import_simkl(token, user_id, mode, username=None):  # noqa: ARG001
    """Celery task for importing media data from SIMKL."""
    return import_media(simkl.importer, token, user_id, mode)


@shared_task(name="Import from MyAnimeList")
def import_mal(username, user_id, mode):
    """Celery task for importing anime and manga data from MyAnimeList."""
    return import_media(mal.importer, username, user_id, mode)


@shared_task(name="Import from AniList")
def import_anilist(user_id, mode, token=None, username=None):
    """Celery task for importing media data from AniList."""
    return import_media(anilist.importer, token, user_id, mode, username)


@shared_task(name="Import from Kitsu")
def import_kitsu(username, user_id, mode):
    """Celery task for importing anime and manga data from Kitsu."""
    return import_media(kitsu.importer, username, user_id, mode)


@shared_task(name="Import from Yamtrack")
def import_yamtrack(file, user_id, mode):
    """Celery task for importing media data from Yamtrack."""
    return import_media(yamtrack.importer, file, user_id, mode)


@shared_task(name="Import from HowLongToBeat")
def import_hltb(file, user_id, mode):
    """Celery task for importing media data from HowLongToBeat."""
    return import_media(hltb.importer, file, user_id, mode)


@shared_task(name="Import from Steam")
def import_steam(username, user_id, mode):
    """Celery task for importing game data from Steam."""
    return import_media(steam.importer, username, user_id, mode)


@shared_task(name="Import from IMDB")
def import_imdb(file, user_id, mode):
    """Celery task for importing media data from IMDB."""
    return import_media(imdb.importer, file, user_id, mode)


@shared_task(name="Import from GoodReads")
def import_goodreads(file, user_id, mode):
    """Celery task for importing media data from GoodReads."""
    return import_media(goodreads.importer, file, user_id, mode)


# --------------------------------------------------------------------------- #
# Crunchyroll forward sync (E9b) — daily watchlist->status + history->progress
# --------------------------------------------------------------------------- #

CR_FAIL_STREAK_KEY = "cr:sync:auth_fail_streak"


def resolve_cr_user():
    """Return the Django user CR sync writes to, or ``None`` if ambiguous.

    CR is single-account/single-profile, so it maps to one fork user. Prefer the
    configured ``CRUNCHYROLL_USERNAME``; otherwise, if the install has exactly one user
    (the personal-fork norm), use it. An empty setting with multiple users is ambiguous
    -> ``None`` (the caller skips rather than guessing whose library to write).
    """
    user_model = get_user_model()
    username = settings.CRUNCHYROLL_USERNAME
    if username:
        return user_model.objects.filter(username=username).first()
    users = list(user_model.objects.all()[:2])
    return users[0] if len(users) == 1 else None


def mint_with_renewal(etp_rt, profile_id=None):
    """Mint a token, auto-rotating ``etp_rt`` via account login on auth failure (E9.5).

    First tries :func:`client.mint_token`. If it raises a credential error
    (:func:`client.is_auth_error` — an expired/revoked ``etp_rt`` surfaces as
    ``invalid_grant``) **and** ``CRUNCHYROLL_ACCOUNT_USERNAME``/``PASSWORD`` are
    configured, this logs in via :func:`client.account_login`, persists the fresh
    cookie to :func:`store.set_etp_rt`, and re-mints with the rotated cookie. Any other
    error re-raises untouched. Fully self-healing: a dead cookie no longer needs a
    manual browser re-capture (the failure-streak toast only fires if login *also*
    fails).
    """
    try:
        return client.mint_token(etp_rt, profile_id=profile_id)
    except (ValueError, OSError) as exc:
        account_user = getattr(settings, "CRUNCHYROLL_ACCOUNT_USERNAME", "")
        account_pass = getattr(settings, "CRUNCHYROLL_ACCOUNT_PASSWORD", "")
        if not (account_user and account_pass and client.is_auth_error(exc)):
            raise
        logger.info(
            "Crunchyroll etp_rt expired; auto-renewing via account login (%s)",
            account_user,
        )
        fresh = client.account_login(account_user, account_pass)
        store.set_etp_rt(fresh["etp_rt"], fresh.get("etp_rt_vid"))
        return client.mint_token(fresh["etp_rt"], profile_id=profile_id)


def run_crunchyroll_sync(user, etp_rt, profile_id):
    """Mint a profile-bound token, guard the profile, then run C2 + C3 for ``user``.

    Shared by the daily beat and the manual management command. Raises ``ValueError`` /
    ``OSError`` on any auth/profile failure (token mint, account lookup, or a profile
    that can't be confirmed) so the caller can record/report it; returns
    ``{"c2": …, "c3": …}`` counts on success. ``etp_rt`` is auto-renewed on expiry via
    :func:`mint_with_renewal` when the account credential is configured (E9.5).

    The token is wrapped in a :class:`client.Token` so a 401 mid-run (the short-lived
    access token expiring during the long C3 phase) transparently re-mints and retries
    instead of erroring on every later call.
    """
    token = client.Token(
        mint_with_renewal(etp_rt, profile_id),
        lambda: mint_with_renewal(etp_rt, profile_id),
    )
    account = client.account_id(token)
    # Mandatory shared-account guard: never write another profile's data.
    if not client.confirm_profile(token, profile_id):
        msg = (
            "Crunchyroll profile could not be confirmed (the token resolved to a "
            "different profile); skipping sync to avoid writing the wrong data."
        )
        raise ValueError(msg)
    return {
        "c2": sync.sync_c2_status(token, account, user),
        "c3": sync.sync_c3_progress(token, account, user),
    }


def _record_cr_failure(user, message):
    """Count a consecutive CR auth/profile failure; surface it once it's persistent.

    A single transient failure (expired ``etp_rt``, a CR blip) only logs. Once the
    streak reaches ``CRUNCHYROLL_AUTH_FAIL_THRESHOLD`` it also raises a persistent
    ``UserMessage`` (error toast) so an unattended beat can't fail silently forever
    (review finding A-fail). The streak resets on the next success.
    """
    streak = (cache.get(CR_FAIL_STREAK_KEY) or 0) + 1
    cache.set(CR_FAIL_STREAK_KEY, streak, None)
    logger.warning("Crunchyroll sync failure (streak %s): %s", streak, message)
    if streak >= settings.CRUNCHYROLL_AUTH_FAIL_THRESHOLD:
        # Failing this far means either auto-renewal isn't configured, or a login
        # also failed — so the guidance covers both recovery paths.
        hint = (
            "Set CRUNCHYROLL_ACCOUNT_USERNAME/PASSWORD to auto-rotate "
            "(or re-capture CRUNCHYROLL_ETP_RT)."
        )
        UserMessage.objects.create(
            user=user,
            level=UserMessageLevel.ERROR.value,
            message=(
                f"Crunchyroll sync has failed {streak} runs in a row. "
                f"{hint} Details: {message}"
            ),
        )


def _clear_cr_failure():
    """Reset the consecutive-failure streak after a successful sync."""
    cache.delete(CR_FAIL_STREAK_KEY)


@shared_task(name="Sync Crunchyroll")
def sync_crunchyroll():
    """Daily: pull CR watchlist->status (C2) and history->progress (C3) for the user.

    No-ops cleanly when CR isn't configured (``ETP_RT``/``PROFILE_ID`` unset) or the
    target user is ambiguous. Reads ``etp_rt`` from the DB store (env-seeded once);
    an expired cookie auto-rotates via account login when configured (E9.5). Auth/
    profile failures are recorded (and surfaced as a persistent error after a few
    consecutive runs) rather than raising.
    """
    if not settings.CRUNCHYROLL_PROFILE_ID:
        logger.info("Crunchyroll sync skipped: PROFILE_ID not configured.")
        return None

    etp_rt = store.resolve_etp_rt()
    if not etp_rt:
        logger.info("Crunchyroll sync skipped: no ETP_RT (env or stored).")
        return None

    user = resolve_cr_user()
    if user is None:
        logger.warning(
            "Crunchyroll sync skipped: no target user (set CRUNCHYROLL_USERNAME).",
        )
        return None

    try:
        result = run_crunchyroll_sync(user, etp_rt, settings.CRUNCHYROLL_PROFILE_ID)
    except (ValueError, OSError) as exc:
        _record_cr_failure(user, str(exc))
        return None

    _clear_cr_failure()
    logger.info("Crunchyroll sync complete: %s", result)
    return result
