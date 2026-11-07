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
    friends = models.ManyToManyField('self', blank=True)

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

    def __str__(self):
        return self.username


class FriendRequest(models.Model):
    """A pending friend request. Deleted once accepted or declined."""

    from_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_friend_requests')
    to_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_friend_requests')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['from_user', 'to_user'], name='unique_friend_request'),
        ]

    def __str__(self):
        return f'{self.from_user} -> {self.to_user}'


class Boardgame(models.Model):
    """
    A game in the shared catalog that players pick from when adding to their profile.

    Rows are imported from Wikidata (external_id is the Wikidata id such as
    "Q17271", cover_url points at Wikimedia Commons; see game_api.py) or are
    added by a user (created_by set, cover is an uploaded image).
    """

    GENRE_CHOICES = User.GENRE_CHOICES

    # Filter key -> (label, condition on the game's player range).
    PLAYER_FILTERS = {
        'single': ('Single player', Q(min_players__lte=1)),
        'two': ('2 players', Q(min_players__lte=2, max_players__gte=2)),
        'up_to_4': ('1-4 players', Q(max_players__lte=4)),
        'five_plus': ('5+ players', Q(max_players__gte=5)),
    }

    external_id = models.CharField(
        max_length=64, null=True, blank=True, unique=True,
        help_text="Wikidata id (e.g. Q17271), for imported games.",
    )
    name = models.CharField(max_length=150)
    cover = models.ImageField(
        upload_to='boardgame_covers/',
        blank=True,
        validators=[validate_image_size],
        help_text="Uploaded cover for games added by users (max 5 MB).",
    )
    cover_url = models.URLField(max_length=500, blank=True, help_text="Cover image URL, for imported games.")
    min_players = models.PositiveSmallIntegerField(null=True, blank=True)
    max_players = models.PositiveSmallIntegerField(null=True, blank=True)
    # Genre keys wrapped in commas (",party,family,") so one genre can be
    # matched with genres__contains=",party," without catching a longer key.
    genres = models.CharField(max_length=200, blank=True)
    rating = models.FloatField(null=True, blank=True, help_text="Rating out of 10. Wikidata has no ratings, so imported games leave it empty.")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='created_boardgames',
    )
    fetched_at = models.DateTimeField(null=True, blank=True, help_text="Last refreshed from Wikidata.")

    class Meta:
        ordering = [models.F('rating').desc(nulls_last=True), 'name']
        constraints = [
            models.CheckConstraint(
                condition=Q(min_players__isnull=True) | Q(max_players__isnull=True)
                | Q(min_players__lte=models.F('max_players')),
                name='boardgame_min_players_lte_max',
            ),
        ]

    @staticmethod
    def format_genres(genre_keys):
        keys = [key for key in genre_keys if key]
        return f",{','.join(keys)}," if keys else ''

    @classmethod
    def genre_filter(cls, genre_key):
        return Q(genres__contains=f',{genre_key},')

    @property
    def genre_keys(self):
        return [key for key in self.genres.split(',') if key]

    @property
    def genre_labels(self):
        labels = dict(self.GENRE_CHOICES)
        return [labels.get(key, key) for key in self.genre_keys]

    @property
    def cover_src(self):
        return self.cover.url if self.cover else self.cover_url

    @property
    def players_display(self):
        low, high = self.min_players, self.max_players
        if not low and not high:
            return 'Players unknown'
        if not low or not high or low == high:
            count = low or high
            return f"{count} player{'s' if count != 1 else ''}"
        return f'{low}-{high} players'

    def save(self, *args, **kwargs):
        self.name = ' '.join(self.name.split())
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


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
    boardgame = models.ForeignKey(
        Boardgame,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='profile_entries',
        help_text="The catalog game this entry was picked from, if any.",
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

    @property
    def picture_src(self):
        """The user's own picture, else the catalog cover, else ''."""
        if self.picture:
            return self.picture.url
        return self.boardgame.cover_src if self.boardgame else ''

    def __str__(self):
        return f'{self.user} - {self.name}'

