"""Crunchyroll sync integration (E9).

Self-contained CR integration kept out of upstream core so an upstream merge rarely
collides (see CLAUDE.md -> "Fork strategy"). Phased by risk:

* **E9a (this phase):** C1 catalog dub/sub -> ``AnimeAvailability``. A one-off backfill
  (``manage.py backfill_crunchyroll_availability``), profile-independent, read-only on
  CR. Modules: ``client`` (token mint + catalog/series fetch) and ``sync``
  (``backfill_c1``); seed map under ``data/cr_mal_map.json``.
* **E9b (deferred):** C2 watchlist -> status, C3 history -> progress. Adds the token
  refresh loop, shared-account profile selection + guard, the CR-code -> MAL-id
  resolver, and a daily Celery beat.

All CR-API-shape risk is isolated in ``client``; everything network is mocked in tests.
"""
