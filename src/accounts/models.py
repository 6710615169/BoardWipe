from django.db import models
from django.contrib.auth.models import AbstractUser


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
        max_length=500,
        blank=True,
        help_text="A short description about yourself.",
    )

    def get_display_name(self):
        """Return display_name if set, otherwise fall back to username."""
        return self.display_name or self.username

    def known_boardgames_list(self):
        """Return known_boardgames as a clean list of names."""
        return [g.strip() for g in self.known_boardgames.split(',') if g.strip()]

    def __str__(self):
        return self.username
