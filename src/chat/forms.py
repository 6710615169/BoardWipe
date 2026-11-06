from django import forms

from .models import Message


class MessageForm(forms.ModelForm):
    """Write a message to a friend."""

    class Meta:
        model = Message
        fields = ['body']
        labels = {'body': 'Message'}
        help_texts = {'body': 'Type @ to tag a boardgame from either profile.'}
        error_messages = {'body': {'required': 'Write a message.'}}
        widgets = {
            'body': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, sender, recipient, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.sender = sender
        self.instance.recipient = recipient
