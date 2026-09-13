from django import forms
from .models import User


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
