"""Shared pytest fixtures for the app test suite."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _stub_mydublist_on_add():
    """Keep the on-add dub-availability fetch from hitting the network in tests.

    Tracking an anime fires a ``post_save(Anime)`` signal that enqueues a
    best-effort MyDubList lookup, run eagerly (``CELERY_TASK_ALWAYS_EAGER``) during
    tests. Default it to a miss so the broad suite stays offline + deterministic;
    tests that actually exercise the fetch patch ``app.tasks.mydublist.get_locales``
    (or ``fetch_dataset``) themselves, which stacks over this stub.
    """
    with patch("app.tasks.mydublist.get_locales", return_value=None):
        yield
