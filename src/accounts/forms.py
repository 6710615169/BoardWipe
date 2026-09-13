from django import forms
from django.contrib.auth.forms import UserCreationForm

from .models import User


class RegisterForm(UserCreationForm):
    """Sign-up form: username + email on top of Django's password handling."""

    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def clean_username(self):
        """
        Reject a username that differs from an existing one only by case.

        Django's default check is case-sensitive, which would let 'Alice' and
        'alice' coexist and confuse people signing in. Keep the iexact lookup.
        """
        username = self.cleaned_data['username']
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('Username already exists.')
        return username


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
        """Reject an email already used by someone else. Blank is allowed for anyone."""
        email = self.cleaned_data.get('email', '')
        if email and User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError('A user with that email already exists.')
        return email
