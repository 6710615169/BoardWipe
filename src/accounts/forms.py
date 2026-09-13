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

    def clean_email(self):
        """Blank is allowed here; the profile form does not require an email."""
        return validate_email_is_unused(self.cleaned_data.get('email', ''), exclude_pk=self.instance.pk)
