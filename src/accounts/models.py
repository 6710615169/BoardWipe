from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.contrib.auth.models import AbstractUser

from .validators import validate_image_size


class User(AbstractUser):
    """Custom user with extra profile fields for the boardgame community."""

    GENRE_CHOICES = [
        ('strategy', 'Strategy'),
        ('party', 'Party'),
        ('cooperative', 'Cooperative'),
        ('family', 'Family'),
        ('card_game', 'Card Game'),
        ('war_game', 'War Game'),
        ('rpg', 'Role-Playing'),
        ('other', 'Other'),
    ]

    display_name = models.CharField(
        max_length=50,
        blank=True,
        help_text="The name shown to other users instead of your username.",
    )
    favorite_boardgame = models.CharField(
        max_length=150,
        blank=True,
        help_text="The boardgame you enjoy the most.",
    )
    favorite_genre = models.CharField(
        max_length=20,
        choices=GENRE_CHOICES,
        blank=True,
        help_text="The genre of boardgame you like best.",
    )
    known_boardgames = models.TextField(
        blank=True,
        help_text="Comma-separated list of boardgames you know how to play, e.g. 'Catan, Chess, Codenames'.",
    )
    bio = models.TextField(
        # Django enforces max_length only in form/model validation, not at the database level.
        max_length=500,
        blank=True,
        help_text="A short description about yourself.",
    )
    profile_picture = models.ImageField(
        upload_to='profile_pictures/',
        blank=True,
        validators=[validate_image_size],
        help_text="Upload a profile picture for your account (max 5 MB).",
    )

    class Meta(AbstractUser.Meta):
        constraints = [
            # Case-insensitive uniqueness that ignores blank emails, because
            # many users may legitimately have no email. Backs up the
            # form-level check in accounts.forms.validate_email_is_unused,
            # and covers the admin, createsuperuser and concurrent signups.
            models.UniqueConstraint(
                Lower('email'),
                condition=~models.Q(email=''),
                name='accounts_user_email_ci_unique_nonblank',
                violation_error_message='A user with that email already exists.',
            ),
        ]

    def get_display_name(self):
        """Return display_name if set, otherwise fall back to username."""
        return self.display_name or self.username

    def known_boardgames_list(self):
        """Return known_boardgames as a clean list of names."""
        return [g.strip() for g in self.known_boardgames.split(',') if g.strip()]

    def __str__(self):
        return self.username


class ProfileBoardgame(models.Model):
    """A boardgame on a user's profile: one row per game, with their own picture."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile_boardgames',
    )
    name = models.CharField(
        max_length=150,
        help_text="The boardgame's name.",
    )
    picture = models.ImageField(
        upload_to='boardgame_pictures/',
        blank=True,
        help_text="Your own picture of this boardgame.",
    )
    is_known = models.BooleanField(
        default=True,
        help_text="You know how to play this boardgame.",
    )
    is_owned = models.BooleanField(
        default=False,
        help_text="You own a copy of this boardgame.",
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']
        constraints = [
            # One row per game per user, so the same game cannot appear twice
            # with different pictures.
            models.UniqueConstraint('user', Lower('name'), name='unique_profile_boardgame_name_ci'),
            # A row that is neither known nor owned has no reason to exist.
            models.CheckConstraint(
                condition=Q(is_known=True) | Q(is_owned=True),
                name='profile_boardgame_known_or_owned',
            ),
        ]

    def save(self, *args, **kwargs):
        # Trim and collapse inner whitespace so " catan " collides with "Catan".
        self.name = ' '.join(self.name.split())
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.user} - {self.name}'
