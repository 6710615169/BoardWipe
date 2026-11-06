from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from .forms import MessageForm
from .models import Message


def get_friend_or_404(user, username):
    # Looking only among the user's friends turns anyone else into a 404, so
    # the URL does not reveal whether a conversation exists.
    return get_object_or_404(user.friends.filter(is_active=True), username=username)


def messages_between(user, friend):
    return Message.objects.filter(
        Q(sender=user, recipient=friend) | Q(sender=friend, recipient=user)
    ).select_related('sender')


@login_required
def conversation_view(request, username):
    """
    Show the message history with a friend and let the user write to them.

    GET  -> render the history and an empty form.
    POST -> validate and save, then redirect back so a reload cannot resend.
    """
    friend = get_friend_or_404(request.user, username)

    if request.method == 'POST':
        form = MessageForm(request.POST, sender=request.user, recipient=friend)
        if form.is_valid():
            form.save()
            return redirect('chat:conversation', username=friend.username)
    else:
        form = MessageForm(sender=request.user, recipient=friend)

    return render(request, 'chat/conversation.html', {
        'friend': friend,
        'chat_messages': messages_between(request.user, friend),
        'form': form,
    })


@login_required
@require_GET
def new_messages_view(request, username, after_id):
    """Return the messages newer than after_id, for the conversation page to poll."""
    friend = get_friend_or_404(request.user, username)
    return render(request, 'chat/_messages.html', {
        'chat_messages': messages_between(request.user, friend).filter(id__gt=after_id),
    })
