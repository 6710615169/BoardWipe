from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import ProfileBoardgame, User


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


class ProfileBoardgameForm(forms.ModelForm):
    """
    Add a boardgame to the given user's profile.

    The one-game-per-user rule is checked here because the form has no user
    field, and Django skips constraints that involve fields missing from the form.
    """

    class Meta:
        model = ProfileBoardgame
        fields = ["name", "picture", "is_known", "is_owned"]
        labels = BOARDGAME_FLAG_LABELS

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.user = user

    def clean_name(self):
        # Match the model's save() so " catan " is checked as "catan".
        name = " ".join(self.cleaned_data["name"].split())
        if ProfileBoardgame.objects.filter(
            user=self.instance.user, name__iexact=name
        ).exists():
            raise forms.ValidationError(
                "This game is already on your profile. Edit it to change the picture."
            )
        return name

    def clean(self):
        cleaned_data = super().clean()
        validate_known_or_owned(self)
        return cleaned_data


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
