"""MyDubList dub-availability source for anime.

MyDubList (https://mydublist.com · github.com/Joelis57/MyDubList · CC BY 4.0)
maintains a daily-updated, multi-language anime **dub** database. Schema verified
2026-06-20.

The on-disk layout is **inverted** vs. a simple ``{mal_id: locales}`` map — it
ships one file per (confidence, language)::

    dubs/confidence/<confidence>/dubbed_<lang>.json
      {"language": "English", "dubbed": [<mal_id>, ...], "partial": [<mal_id>, ...]}

* ``<confidence>`` ∈ ``low`` (≥1 source) · ``normal`` (≥2) · ``high`` (≥3) ·
  ``very-high`` (≥4). The maintainer chose ``high`` (``MYDUBLIST_CONFIDENCE``).
* ``<lang>`` is a lowercase English language **name** (``english``, ``spanish``),
  NOT a locale code — see ``LANG_TO_LOCALE``.
* ``dubbed`` (full) and ``partial`` (some episodes) both count as available — the
  maintainer's call; a partial dub is still a dub you can start.
* Only **dub** data exists here — subtitle availability is never sourced from
  MyDubList (``AnimeAvailability.subtitle_locales`` stays manual until E9).

``fetch_dataset`` downloads every language file for one confidence tier and
**inverts** them into ``{str(mal_id): [canonical locale code, ...]}`` (codes from
``app/languages.py``; keyed by ``str`` to match ``Item.media_id``, a
``CharField``). The download is all-or-nothing: if any file fails (HTTP error, bad
JSON, schema drift) the whole fetch raises and nothing is cached, so a flaky run
leaves prior availability **stale-but-intact** rather than partially blanked.

Attribution (CC BY 4.0, required when displaying the data): see ``ATTRIBUTION``.
"""

import logging

from django.conf import settings
from django.core.cache import cache

from app import languages
from app.providers import services

logger = logging.getLogger(__name__)

BASE_URL = "https://raw.githubusercontent.com/Joelis57/MyDubList/main/dubs/confidence"
PROVIDER = "mydublist"
ATTRIBUTION = "Dub data © MyDubList - https://mydublist.com - (CC BY 4.0)"

CONFIDENCE_LEVELS = ("low", "normal", "high", "very-high")
DEFAULT_CONFIDENCE = "high"
CACHE_TTL = 60 * 60 * 24  # 24h — MyDubList updates daily.

# MyDubList lowercase language name -> our canonical CR/BCP-47 locale code.
# MyDubList does NOT distinguish dub regions (one "Spanish"/"Portuguese"/"Chinese"
# list each), so those collapse to the dominant anime-dub region (es-419 / pt-BR /
# zh-CN) using codes already in languages.LOCALE_DISPLAY — best-effort labels a
# manual edit or Crunchyroll (E9) can refine per-title. The 9 languages absent from
# the v1 map (danish, dutch, …) get plain BCP-47 codes; they're not in
# LOCALE_DISPLAY so the badge shows the raw code (visible, not dropped) for now.
LANG_TO_LOCALE = {
    "arabic": "ar-SA",
    "catalan": "ca-ES",
    "chinese": "zh-CN",  # region-collapsed
    "danish": "da-DK",  # not in v1 map
    "dutch": "nl-NL",  # not in v1 map
    "english": "en-US",
    "finnish": "fi-FI",  # not in v1 map
    "french": "fr-FR",
    "german": "de-DE",
    "hebrew": "he-IL",  # not in v1 map
    "hindi": "hi-IN",
    "hungarian": "hu-HU",  # not in v1 map
    "indonesian": "id-ID",
    "italian": "it-IT",
    "japanese": "ja-JP",
    "korean": "ko-KR",
    "lithuanian": "lt-LT",  # not in v1 map
    "norwegian": "nb-NO",  # not in v1 map
    "polish": "pl-PL",
    "portuguese": "pt-BR",  # region-collapsed
    "russian": "ru-RU",
    "spanish": "es-419",  # region-collapsed
    "swedish": "sv-SE",  # not in v1 map
    "tagalog": "tl-PH",  # not in v1 map
    "thai": "th-TH",
    "turkish": "tr-TR",
    "vietnamese": "vi-VN",
}

# Display order for normalize_locales: known codes first (in languages.py order so
# the badge reads Japanese/English/... consistently), unknown codes appended after.
_ORDER = {code: index for index, code in enumerate(languages.LOCALE_DISPLAY)}


def resolve_confidence(confidence=None):
    """Return a valid confidence tier, defaulting to the configured one.

    ``None`` -> ``settings.MYDUBLIST_CONFIDENCE`` (or ``DEFAULT_CONFIDENCE`` if
    unset). Raises ``ValueError`` on an unknown tier so a typo fails loudly instead
    of 404-ing.
    """
    if confidence is None:
        confidence = getattr(settings, "MYDUBLIST_CONFIDENCE", DEFAULT_CONFIDENCE)
    if confidence not in CONFIDENCE_LEVELS:
        msg = (
            f"Unknown MyDubList confidence {confidence!r}; "
            f"expected one of {CONFIDENCE_LEVELS}"
        )
        raise ValueError(msg)
    return confidence


def normalize_locales(codes):
    """Dedupe and stably order a list of locale ``codes``.

    Collapses duplicates (a title can appear in both ``dubbed`` and ``partial`` of
    the same language), orders known codes by ``languages.LOCALE_DISPLAY`` and
    appends unknown codes (passthrough — visible, never dropped) in first-seen
    order. Empty in -> empty out.
    """
    seen = []
    for code in codes:
        if code and code not in seen:
            seen.append(code)
    known = sorted((code for code in seen if code in _ORDER), key=_ORDER.get)
    unknown = [code for code in seen if code not in _ORDER]
    return known + unknown


def _download_language(confidence, lang):
    """Fetch and validate one ``dubbed_<lang>.json`` file for a confidence tier.

    Raises on HTTP/network error (via ``services.api_request``) or schema drift so
    the caller can abort the whole sync without writing partial data.
    """
    url = f"{BASE_URL}/{confidence}/dubbed_{lang}.json"
    payload = services.api_request(PROVIDER, "GET", url)
    if not isinstance(payload, dict) or "dubbed" not in payload:
        msg = f"MyDubList schema drift: 'dubbed' list missing in {url}"
        raise ValueError(msg)
    return payload


def fetch_dataset(confidence=None, *, force_refresh=False):
    """Return ``{str(mal_id): [locale code, ...]}`` of dub availability, cached 24h.

    Downloads all ``len(LANG_TO_LOCALE)`` per-language files for the resolved
    ``confidence`` tier and inverts them into a MAL-id-keyed map (both ``dubbed``
    and ``partial`` count as available). Set ``force_refresh`` (the daily task
    does) to bypass the cache and re-download.

    All-or-nothing: any download/parse/schema failure propagates and leaves the
    cache untouched, so callers never see a partially-built (silently blanked)
    dataset.
    """
    confidence = resolve_confidence(confidence)
    cache_key = f"mydublist_dataset_{confidence}"

    if not force_refresh:
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

    accumulated = {}
    for lang, code in LANG_TO_LOCALE.items():
        payload = _download_language(confidence, lang)
        mal_ids = payload.get("dubbed", []) + payload.get("partial", [])
        for mal_id in mal_ids:
            accumulated.setdefault(str(mal_id), []).append(code)

    dataset = {
        mal_id: normalize_locales(codes) for mal_id, codes in accumulated.items()
    }
    cache.set(cache_key, dataset, CACHE_TTL)
    logger.info(
        "MyDubList: cached %s dubbed titles (confidence=%s)",
        len(dataset),
        confidence,
    )
    return dataset


def get_locales(media_id, confidence=None):
    """Return dub locale codes for one MAL ``media_id``, or ``None`` if not covered.

    ``None`` (no entry) is deliberately distinct from ``[]`` so callers honour the
    never-blank rule: a miss must NOT overwrite a title's existing ``audio_locales``.
    """
    dataset = fetch_dataset(confidence)
    return dataset.get(str(media_id))
