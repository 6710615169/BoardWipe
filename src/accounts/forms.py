from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import transaction
from django.db.models import F
from django.db.models.functions import Lower

from .models import Boardgame, FreeTime, ProfileBoardgame, User


def validate_email_is_unused(email, exclude_pk=None):
    """
    Reject an email already used by another account.

    Registration and profile editing must agree on this: if only one of them
    checks, a duplicate slips in at signup and then locks that user out of
    saving their own profile. Note this is a form-level check with a
    check-then-write race; real enforcement needs unique=True on the model.
    """
    if not email:
        return email
    clash = User.objects.filter(email__iexact=email)
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise forms.ValidationError("A user with that email already exists.")
    return email


class RegisterForm(UserCreationForm):
    """Sign-up form: username + email on top of Django's password handling."""

    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ["username", "email", "password1", "password2"]

    def clean_email(self):
        return validate_email_is_unused(self.cleaned_data.get("email", ""))


class ProfileForm(forms.ModelForm):
    """Form used by a user to view/edit their own profile."""

    class Meta:
        model = User
        fields = [
            "display_name",
            "first_name",
            "last_name",
            "email",
            "favorite_boardgame",
            "favorite_genre",
            "bio",
            "profile_picture",
        ]
        widgets = {
            "bio": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remember the stored picture now: by the time save() runs, the form
        # has already pointed the instance at the new upload (or at '' when
        # "Clear" was ticked), so the old name would be lost.
        self._old_picture_name = (
            self.instance.profile_picture.name if self.instance.pk else ""
        )
        self.fields["favorite_boardgame"] = forms.ChoiceField(
            choices=self._favorite_choices(),
            required=False,
            label="Favorite boardgame",
            help_text="Pick one of the games on your profile.",
        )

    def _favorite_choices(self):
        """The user's own games; an older favorite not on the list stays valid."""
        names = []
        if self.instance.pk:
            names = sorted(
                self.instance.profile_boardgames.values_list("name", flat=True),
                key=str.casefold,
            )
        choices = [("", "No favorite yet")] + [(name, name) for name in names]
        current = self.instance.favorite_boardgame
        same_game = [name for name in names if name.casefold() == current.casefold()]
        if same_game:
            # Select the list entry even if the saved text differs in case.
            self.initial["favorite_boardgame"] = same_game[0]
        elif current:
            choices.append((current, f"{current} (not on your list)"))
        return choices

    def save(self, commit=True):
        user = super().save(commit=commit)
        if commit:
            self._delete_replaced_picture()
        return user

    def _delete_replaced_picture(self):
        """Remove the previous picture file once it has been replaced or cleared.

        With save(commit=False) the caller owns the save, so cleanup is skipped.
        """
        old_name = self._old_picture_name
        picture = self.instance.profile_picture
        if old_name and old_name != picture.name:
            picture.storage.delete(old_name)
        self._old_picture_name = picture.name

    def clean_email(self):
        """Blank is allowed here; the profile form does not require an email."""
        return validate_email_is_unused(
            self.cleaned_data.get("email", ""), exclude_pk=self.instance.pk
        )


class NotificationSettingsForm(forms.ModelForm):
    """Opt in or out of email notifications."""

    class Meta:
        model = User
        fields = ["email_notifications"]
        labels = {"email_notifications": "Email me about new messages and requests"}


BOARDGAME_FLAG_LABELS = {
    "is_known": "I know this game",
    "is_owned": "I own this game",
}


def validate_known_or_owned(form):
    """
    Mirror the model's known-or-owned CheckConstraint with a readable message.

    The error goes on is_known so Django skips its own constraint check (it
    leaves out constraints on fields that already failed) and the user sees
    one message instead of the raw constraint name.
    """
    if not form.cleaned_data.get("is_known") and not form.cleaned_data.get("is_owned"):
        form.add_error(
            "is_known", 'Tick at least one of "I know this game" or "I own this game".'
        )


def normalize_game_name(name):
    """Match ProfileBoardgame.save(), so " catan " is compared as "catan"."""
    return " ".join(name.split())


class BoardgameSearchForm(forms.Form):
    """Search, filter and sort the catalog on the "Add a game" page."""

    SORT_CHOICES = [
        ("rating", "Rating: high to low"),
        ("rating_asc", "Rating: low to high"),
        ("name", "Name: A to Z"),
    ]

    q = forms.CharField(required=False, max_length=100, label="Search")
    genre = forms.ChoiceField(
        required=False, choices=[("", "All genres")] + User.GENRE_CHOICES
    )
    players = forms.ChoiceField(
        required=False,
        choices=[("", "Any number")]
        + [(key, label) for key, (label, _) in Boardgame.PLAYER_FILTERS.items()],
        label="Players",
    )
    sort = forms.ChoiceField(required=False, choices=SORT_CHOICES, label="Sort by")

    def filter_and_sort(self, games):
        """
        Apply the genre/players filters and the sort to a Boardgame queryset.
        Invalid values are ignored. The text search is left to the view, which
        also matches the ids Wikidata returned.
        """
        data = self.cleaned_data if self.is_bound and self.is_valid() else {}
        if data.get("genre"):
            games = games.filter(Boardgame.genre_filter(data["genre"]))
        if data.get("players"):
            games = games.filter(Boardgame.PLAYER_FILTERS[data["players"]][1])
        sort = data.get("sort") or "rating"
        if sort == "name":
            return games.order_by(Lower("name"))
        if sort == "rating_asc":
            return games.order_by(F("rating").asc(nulls_last=True), Lower("name"))
        return games.order_by(F("rating").desc(nulls_last=True), Lower("name"))


class BoardgameCreateForm(forms.ModelForm):
    """
    "Add new": put a game that is not in the catalog into it, and onto the
    user's profile. Every field is required so the new card is complete.
    """

    genre_choices = forms.MultipleChoiceField(
        choices=User.GENRE_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        label="Genre",
        help_text="Pick one or more.",
        error_messages={"required": "Pick at least one genre."},
    )

    class Meta:
        model = Boardgame
        fields = ["name", "cover", "min_players", "max_players"]
        labels = {
            "name": "Boardgame name",
            "cover": "Game cover",
            "min_players": "Minimum players",
            "max_players": "Maximum players",
        }

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        for name in ("cover", "min_players", "max_players"):
            self.fields[name].required = True
        for name in ("min_players", "max_players"):
            field = self.fields[name]
            # Replace the model field's generic ">= 0" check with one 1-99
            # range, so a bad value shows a single, plain message.
            field.min_value, field.max_value = 1, 99
            field.validators = [
                validator
                for validator in field.validators
                if not isinstance(validator, (MinValueValidator, MaxValueValidator))
            ] + [
                MinValueValidator(1, "A game needs at least 1 player."),
                MaxValueValidator(99, "Enter 99 players or fewer."),
            ]
            field.widget.attrs.update(min=1, max=99)

    def clean_name(self):
        name = normalize_game_name(self.cleaned_data["name"])
        if ProfileBoardgame.objects.filter(user=self.user, name__iexact=name).exists():
            raise forms.ValidationError("This game is already on your profile.")
        return name

    def clean(self):
        cleaned_data = super().clean()
        low, high = cleaned_data.get("min_players"), cleaned_data.get("max_players")
        if low and high and low > high:
            self.add_error(
                "max_players", "Maximum players cannot be less than minimum players."
            )
        return cleaned_data

    @transaction.atomic
    def save(self):
        """Create the catalog game and add it to the user's profile as known."""
        game = super().save(commit=False)
        game.genres = Boardgame.format_genres(self.cleaned_data["genre_choices"])
        game.created_by = self.user
        game.save()
        ProfileBoardgame.objects.create(
            user=self.user, name=game.name, boardgame=game, is_known=True
        )
        return game


class ProfileBoardgameEditForm(forms.ModelForm):
    """
    Change the picture or the known/owned flags of a game already on a profile.

    The name is left out on purpose: renaming would let a user turn one entry
    into a duplicate of another.
    """

    class Meta:
        model = ProfileBoardgame
        fields = ["picture", "is_known", "is_owned"]
        labels = BOARDGAME_FLAG_LABELS

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._old_picture_name = self.instance.picture.name

    def clean(self):
        cleaned_data = super().clean()
        validate_known_or_owned(self)
        return cleaned_data

    def save(self, commit=True):
        game = super().save(commit=commit)
        # Replacing or clearing the picture would otherwise leave the old file
        # orphaned in MEDIA_ROOT.
        if (
            commit
            and self._old_picture_name
            and game.picture.name != self._old_picture_name
        ):
            game.picture.storage.delete(self._old_picture_name)
        return game


class FreeTimeForm(forms.ModelForm):
    class Meta:
        model = FreeTime
        fields = ["date", "start_time", "end_time"]
        widgets = {
            "date": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"type": "date"},
            ),
            "start_time": forms.TimeInput(
                format="%H:%M",
                attrs={"type": "time"},
            ),
            "end_time": forms.TimeInput(
                format="%H:%M",
                attrs={"type": "time"},
            ),
        }
