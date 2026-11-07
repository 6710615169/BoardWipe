"""Email notifications for new messages and friend requests."""

import logging
from datetime import timedelta
from urllib.parse import urljoin

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from .models import ConversationNotification

logger = logging.getLogger(__name__)

PREVIEW_LENGTH = 140


def absolute_url(path):
    return urljoin(settings.SITE_URL.rstrip("/") + "/", path.lstrip("/"))


def make_preview(body):
    """Collapse whitespace and cut long messages so the email shows a short preview."""
    text = " ".join(body.split())
    if len(text) > PREVIEW_LENGTH:
        text = text[: PREVIEW_LENGTH - 1].rstrip() + "…"
    return text


def can_email(user):
    return bool(user.is_active and user.email and user.email_notifications)


def _claim_slot(recipient, sender):
    """
    Decide atomically whether an email may go out now.

    Returns the previous timestamp (None for a first notification) when the
    caller has claimed the slot, or False when the throttle window is still
    open. The conditional UPDATE means two simultaneous messages cannot both
    claim the same slot.
    """
    now = timezone.now()
    cutoff = now - timedelta(minutes=settings.NOTIFICATION_THROTTLE_MINUTES)
    try:
        _, created = ConversationNotification.objects.get_or_create(
            recipient=recipient, sender=sender, defaults={"last_notified_at": now}
        )
    except IntegrityError:  # lost a race to create the row; the other request won
        return False
    if created:
        return None
    previous = ConversationNotification.objects.get(
        recipient=recipient, sender=sender
    ).last_notified_at
    claimed = ConversationNotification.objects.filter(
        recipient=recipient, sender=sender, last_notified_at=previous
    ).filter(last_notified_at__lt=cutoff)
    return previous if claimed.update(last_notified_at=now) else False


def _release_slot(recipient, sender, previous):
    """Undo a claim after a failed send so the next message can try again."""
    queryset = ConversationNotification.objects.filter(
        recipient=recipient, sender=sender
    )
    if previous is None:
        queryset.delete()
    else:
        queryset.update(last_notified_at=previous)


def _send(recipient, subject, template, context):
    context = {
        **context,
        "settings_url": absolute_url(reverse("accounts:profile_settings")),
    }
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string(f"chat/email/{template}.txt", context),
        to=[recipient.email],
    )
    message.attach_alternative(
        render_to_string(f"chat/email/{template}.html", context), "text/html"
    )
    message.send()


def _clean_name(user):
    # Display names go into the subject line, which must stay on one line.
    return " ".join(user.get_display_name().split())


def notify_new_message(message):
    """
    Email the recipient about a new message, at most once per throttle window.

    Never raises: a mail problem must not stop the message from being sent.
    """
    recipient, sender = message.recipient, message.sender
    if not can_email(recipient):
        logger.info(
            "Message email to %s skipped: notifications off or no email", recipient
        )
        return False

    previous = _claim_slot(recipient, sender)
    if previous is False:
        logger.info("Message email to %s skipped: throttled", recipient)
        return False

    try:
        _send(
            recipient,
            subject=f"New message from {_clean_name(sender)} on BoardWipe",
            template="new_message",
            context={
                "recipient": recipient,
                "sender": sender,
                "sender_name": _clean_name(sender),
                "preview": make_preview(message.body),
                "chat_url": absolute_url(
                    reverse("chat:conversation", args=[sender.username])
                ),
            },
        )
    except Exception:  # noqa: BLE001 - SMTP/network errors are many and varied
        logger.exception("Message email to %s failed", recipient)
        _release_slot(recipient, sender, previous)
        return False
    logger.info("Message email to %s sent", recipient)
    return True


def notify_friend_request(friend_request):
    """Email the recipient about a new friend request. Never raises."""
    recipient, sender = friend_request.to_user, friend_request.from_user
    if not can_email(recipient):
        logger.info(
            "Friend request email to %s skipped: notifications off or no email",
            recipient,
        )
        return False
    try:
        _send(
            recipient,
            subject=f"{_clean_name(sender)} sent you a friend request on BoardWipe",
            template="friend_request",
            context={
                "recipient": recipient,
                "sender": sender,
                "sender_name": _clean_name(sender),
                "friends_url": absolute_url(reverse("accounts:friends")),
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("Friend request email to %s failed", recipient)
        return False
    logger.info("Friend request email to %s sent", recipient)
    return True
