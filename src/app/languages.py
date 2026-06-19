"""Canonical locale codes <-> display names — single source of truth.

Ported verbatim from the v1 tracker's verified ``LANGUAGES`` map
(``Media Tracker v1/gas/Crunchy_Global_var.gs``). Codes are CR/BCP-47 style
(``ja-JP``, ``en-US``, ``es-419``) — the exact form Crunchyroll (E9) emits, so
that source is a no-op, and regional dub distinctions (es-419 vs es-ES) survive.

Consumers (keep the reverse map and passthrough rules in ONE place):
  * the dub/sub availability badge — ``display_name(code)``
  * the manual-entry form — ``code_for_display(text)`` (reverse lookup)
  * ``providers/mydublist.normalize_locales`` — validate/label raw codes
  * the E2 language filter — labels + the dropdown's option order
"""

# code -> English display name. Insertion order is preserved (Japanese/English
# first, then by region) and used as-is for the E2 filter dropdown ordering.
LOCALE_DISPLAY = {
    "ja-JP": "Japanese",
    "en-US": "English",
    "en-IN": "English (India)",
    "id-ID": "Indonesian",
    "ms-MY": "Malay",
    "ca-ES": "Catalan",
    "de-DE": "German",
    "es-419": "Spanish (Latin America)",
    "es-ES": "Spanish (Spain)",
    "fr-FR": "French",
    "it-IT": "Italian",
    "pl-PL": "Polish",
    "pt-BR": "Portuguese (Brazil)",
    "pt-PT": "Portuguese (Portugal)",
    "vi-VN": "Vietnamese",
    "tr-TR": "Turkish",
    "ru-RU": "Russian",
    "ar-SA": "Arabic",
    "hi-IN": "Hindi",
    "ta-IN": "Tamil",
    "te-IN": "Telugu",
    "zh-CN": "Chinese (Simplified)",
    "zh-HK": "Chinese (Cantonese)",
    "zh-TW": "Chinese (Traditional)",
    "ko-KR": "Korean",
    "th-TH": "Thai",
}

# Reverse index for the manual form, keyed on a normalized (casefolded) display
# name. Built once from LOCALE_DISPLAY so there is no second list to keep in sync.
_DISPLAY_TO_CODE = {name.casefold(): code for code, name in LOCALE_DISPLAY.items()}

# Casefolded code -> canonical code, so a known code typed in the wrong case
# (e.g. "JA-JP") still resolves instead of falling through to the form's
# code-shaped passthrough (which requires a lowercase language prefix).
_CASEFOLDED_CODE = {code.casefold(): code for code in LOCALE_DISPLAY}


def display_name(code):
    """Return the English display name for a locale ``code``.

    Unknown codes pass through unchanged so an unmapped value from a source is
    shown raw (visible, not swallowed) rather than dropped.
    """
    return LOCALE_DISPLAY.get(code, code)


def code_for_display(text):
    """Resolve a user-typed language to its canonical code, or ``None``.

    Accepts either a display name (``"Spanish (Latin America)"``) or a locale
    code already in the map (``"es-419"``); matching is case-insensitive and
    whitespace-trimmed. Returns ``None`` when nothing matches so callers (the
    manual form) can raise a clear validation error.
    """
    cleaned = text.strip()
    if cleaned in LOCALE_DISPLAY:  # already a known code
        return cleaned
    code = _CASEFOLDED_CODE.get(cleaned.casefold())
    if code is not None:
        return code
    return _DISPLAY_TO_CODE.get(cleaned.casefold())
