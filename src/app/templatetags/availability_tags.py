"""Template filters for dub/sub availability (E1).

Kept in a dedicated module (not app_tags.py) so an upstream merge never
collides with Yamtrack's own template tags.
"""

from django import template

from app import languages

register = template.Library()


@register.filter
def locale_display(code):
    """Map a canonical locale code to its English display name.

    Unknown codes pass through unchanged so an unmapped value is shown raw.
    """
    return languages.display_name(code)
