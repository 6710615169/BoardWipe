from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


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
        raise forms.ValidationError('A user with that email already exists.')
    return email


class RegisterForm(UserCreationForm):
    """Sign-up form: username + email on top of Django's password handling."""

    email = forms.EmailField(required=True)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def clean_email(self):
        return validate_email_is_unused(self.cleaned_data.get('email', ''))


class ProfileForm(forms.ModelForm):
    """Form used by a user to view/edit their own profile."""

    class Meta:
        model = User
        fields = [
            'display_name',
            'first_name',
            'last_name',
            'email',
            'favorite_boardgame',
            'favorite_genre',
            'known_boardgames',
            'bio',
            'profile_picture',
        ]
        widgets = {
            'known_boardgames': forms.Textarea(attrs={'rows': 3, 'placeholder': 'Catan, Chess, Codenames'}),
            'bio': forms.Textarea(attrs={'rows': 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remember the stored picture now: by the time save() runs, the form
        # has already pointed the instance at the new upload (or at '' when
        # "Clear" was ticked), so the old name would be lost.
        self._old_picture_name = self.instance.profile_picture.name if self.instance.pk else ''

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
        return validate_email_is_unused(self.cleaned_data.get('email', ''), exclude_pk=self.instance.pk)
