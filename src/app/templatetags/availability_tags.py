"""Template filters for dub/sub availability (E1).

Kept in a dedicated module (not app_tags.py) so an upstream merge never
collides with Yamtrack's own template tags.
"""

from django import template

from app import languages
from app.models import AvailabilitySource
from app.providers import mydublist

register = template.Library()


@register.filter
def locale_display(code):
    """Map a canonical locale code to its English display name.

    Unknown codes pass through unchanged so an unmapped value is shown raw.
    """
    return languages.display_name(code)


@register.simple_tag
def mydublist_credit(source):
    """Return MyDubList's CC BY 4.0 credit line for MyDubList-sourced availability.

    Empty string for other sources (manual / Crunchyroll), which need no MyDubList
    attribution. CC BY 4.0 *requires* this line wherever the dub data is displayed.
    """
    if source == AvailabilitySource.MYDUBLIST.value:
        return mydublist.ATTRIBUTION
    return ""
