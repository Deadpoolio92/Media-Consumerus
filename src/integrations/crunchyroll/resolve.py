"""CR series-code <-> MAL-id resolution.

**E9a surface (this phase):** the static seed map only. ``data/cr_mal_map.json`` was
built from E10's ``resolved.json`` (the maintainer's own library, Jikan+TMDB resolved):
307 anime at confidence high/override/medium; **low-confidence excluded** (the
skip-don't-guess rule). C1 uses :func:`mal_to_cr` to find a library item's CR code.

**E9b will add** ``cr_code_to_mal(code, title)`` — seed hit, then a Jikan-search
fallback (port of E10's scorer) with a resolution cache — needed for C2/C3 (watchlist
and history arrive in CR's id space). It is deliberately NOT built yet: C1 never needs
CR -> MAL (it already has the library item's MAL id and only needs its CR code).
"""

import json
from functools import lru_cache
from pathlib import Path

SEED_PATH = Path(__file__).parent / "data" / "cr_mal_map.json"


@lru_cache(maxsize=1)
def load_cr_mal_map():
    """Return the static ``{cr_code: mal_id}`` seed (both values are ``str``).

    Cached for the process; the file is static. Treat the result as read-only.
    """
    with SEED_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def mal_to_cr():
    """Return the inverse ``{mal_id: cr_code}`` map (the seed is 1:1, verified).

    C1's lookup direction: a library anime is keyed by MAL id and needs its CR code to
    find the catalog entry. Treat the result as read-only.
    """
    return {mal_id: code for code, mal_id in load_cr_mal_map().items()}
