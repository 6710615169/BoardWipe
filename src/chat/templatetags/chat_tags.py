import re

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def highlight_boardgames(body, names):
    """Return body as safe HTML, with each @mention of the given boardgame names highlighted."""
    if not names:
        return escape(body)
    # Longest first, so "@Ticket to Ride" is not read as a mention of "Ticket".
    # Names may contain spaces, so they are matched as whole phrases, and the
    # lookarounds keep "me@catan.com" and "@Catan2" from counting as "Catan".
    alternatives = '|'.join(re.escape(name) for name in sorted(names, key=len, reverse=True))
    # With a capture group, split() puts the mentioned names at odd indexes.
    parts = re.split(rf'(?<!\w)@({alternatives})(?!\w)', body, flags=re.IGNORECASE)
    return mark_safe(''.join(
        format_html('<span class="chat-mention">@{}</span>', part) if index % 2 else escape(part)
        for index, part in enumerate(parts)
    ))
