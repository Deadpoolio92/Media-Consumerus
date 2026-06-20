"""Shared pytest fixtures for the app test suite."""

from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _stub_on_add_fetches():
    """Keep the best-effort on-add fetches from hitting the network in tests.

    Tracking media fires ``post_save`` signals that enqueue best-effort lookups,
    run eagerly (``CELERY_TASK_ALWAYS_EAGER``) during tests:
      * anime → MyDubList dub availability (``app.tasks.mydublist.get_locales``);
      * filterable media → catalog genre/year (``app.metadata_fields.fetch_for_item``).
    Default both to a miss so the broad suite stays offline + deterministic; tests
    that actually exercise a fetch patch the relevant symbol themselves, which
    stacks over these stubs.
    """
    with (
        patch("app.tasks.mydublist.get_locales", return_value=None),
        patch("app.tasks.metadata_fields.fetch_for_item", return_value=None),
    ):
        yield
