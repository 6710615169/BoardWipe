from django import forms

from accounts.models import ProfileBoardgame

from .models import Message


def taggable_boardgames(user, friend):
    """Return the sorted names of both people's games, without case-only duplicates."""
    names = ProfileBoardgame.objects.filter(user__in=[user, friend]).values_list('name', flat=True)
    unique_names = {name.casefold(): name for name in names}
    return sorted(unique_names.values(), key=str.casefold)


class MessageForm(forms.ModelForm):
    """Write a message to a friend, optionally tagging a boardgame."""

    tagged_boardgame = forms.ChoiceField(required=False, label='Tag a boardgame')

    class Meta:
        model = Message
        fields = ['body', 'tagged_boardgame']
        labels = {'body': 'Message'}
        widgets = {
            'body': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, sender, recipient, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.sender = sender
        self.instance.recipient = recipient
        names = taggable_boardgames(sender, recipient)
        self.fields['tagged_boardgame'].choices = [('', 'No boardgame')] + [(name, name) for name in names]

    def clean(self):
        cleaned_data = super().clean()
        if not self.errors and not cleaned_data['body'] and not cleaned_data['tagged_boardgame']:
            self.add_error('body', 'Write a message or tag a boardgame.')
        return cleaned_data
