import re

from django import template
from django.utils.html import escape, format_html, format_html_join

register = template.Library()


@register.filter
def highlight_boardgames(body, names):
    """Return body as safe HTML, with @mentions of the given boardgames highlighted."""
    if not names:
        return escape(body)
    # Longest first, so "@Ticket to Ride" is not read as a mention of "Ticket".
    # Names may contain spaces, so they are matched as whole phrases, and the
    # lookarounds keep "me@catan.com" and "@Catan2" from counting as "Catan".
    alternatives = "|".join(
        re.escape(name) for name in sorted(names, key=len, reverse=True)
    )
    # With a capture group, split() puts the mentioned names at odd indexes.
    parts = re.split(rf"(?<!\w)@({alternatives})(?!\w)", body, flags=re.IGNORECASE)
    mention = '<span class="chat-mention">@{}</span>'
    # format_html_join escapes the plain text and leaves the mention spans intact.
    return format_html_join(
        "",
        "{}",
        (
            (format_html(mention, part) if index % 2 else part,)
            for index, part in enumerate(parts)
        ),
    )
