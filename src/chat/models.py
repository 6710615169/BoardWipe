from django.conf import settings
from django.db import models


class Message(models.Model):
    """One message sent from a user to one of their friends."""

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_messages",
    )
    body = models.TextField(
        # Django enforces max_length only in form/model validation, not at the
        # database level.
        max_length=1000,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.sender} -> {self.recipient}: {self.body[:30]}"


class ConversationNotification(models.Model):
    """
    When the recipient was last emailed about messages from one sender.

    One row per (recipient, sender) direction. It is the throttle: a burst of
    messages sends one email, not one per message.
    """

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )
    last_notified_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "sender"],
                name="unique_conversation_notification",
            ),
        ]

    def __str__(self):
        return f"{self.sender} -> {self.recipient} at {self.last_notified_at}"
