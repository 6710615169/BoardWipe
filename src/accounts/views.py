from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import ProfileForm


@login_required
def profile_view(request):
    """
    Show the logged-in user's profile and let them edit it in place.

    GET  -> render the profile with a bound form showing current values.
    POST -> validate and save changes, then redisplay the (now updated) profile.
    """
    user = request.user

    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('accounts:profile')
    else:
        form = ProfileForm(instance=user)

    context = {
        'form': form,
        'profile_user': user,
        'known_boardgames_list': user.known_boardgames_list(),
    }
    return render(request, 'accounts/profile.html', context)
