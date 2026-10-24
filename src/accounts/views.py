from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST
from django.db.models import Q
from django.shortcuts import get_object_or_404
from .models import User

from .forms import ProfileForm, RegisterForm

@login_required
def profile_search_view(request):
    q = request.GET.get('q', '').strip()
    genre = request.GET.get('genre', '')
    known = request.GET.get('known', '').strip()
    favorite = request.GET.get('favorite', '').strip()

    users = User.objects.filter(is_active=True).exclude(pk=request.user.pk)

    if q:
        users = users.filter(
            Q(username__icontains=q) |
            Q(display_name__icontains=q) |
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q)
        )
    if genre:
        users = users.filter(favorite_genre=genre)
    if known:
        users = users.filter(known_boardgames__icontains=known)
    if favorite:
        users = users.filter(favorite_boardgame__icontains=favorite)

    return render(request, 'accounts/profile_search.html', {
        'users_found': users.order_by('username'),
        'genre_choices': User.GENRE_CHOICES,
        'q': q, 'genre': genre, 'known': known, 'favorite': favorite,
    })


@login_required
def profile_detail_view(request, username):
    profile_user = get_object_or_404(User, username=username, is_active=True)
    return render(request, 'accounts/profile_detail.html', {'profile_user': profile_user})

def home(request):
    return render(request, 'accounts/home.html')


def register_view(request):
    """Create an account and sign the new user straight in."""
    if request.user.is_authenticated:
        return redirect('accounts:profile')

    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, 'Account created successfully! Welcome.')
            return redirect('accounts:profile')
    else:
        form = RegisterForm()

    return render(request, 'accounts/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('accounts:profile')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            # AuthenticationForm already authenticated the credentials during
            # validation; get_user() returns that user without hashing again.
            login(request, form.get_user())
            # Send the user where they were headed, but only if that target is
            # on this site -- an unchecked ?next= is an open redirect.
            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = AuthenticationForm(request)

    return render(request, 'accounts/login.html', {'form': form, 'next': request.GET.get('next', '')})


@require_POST
def logout_view(request):
    """POST-only, so a stray link or a prefetching browser cannot sign people out."""
    logout(request)
    messages.success(request, 'You have been logged out.')
    return redirect('accounts:home')


@login_required
@require_GET
def profile_view(request):
    """Show the logged-in user's profile. Editing lives on profile_editing_view."""
    user = request.user
    context = {
        'profile_user': user,
        'known_boardgames_list': user.known_boardgames_list(),
    }
    return render(request, 'accounts/profile.html', context)


@login_required
def profile_editing_view(request):
    """
    Let the logged-in user edit their own profile.

    GET  -> render the form filled with the current values.
    POST -> validate and save, then send the user back to their profile.
    """
    if request.method == 'POST':
        form = ProfileForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated.')
            return redirect('accounts:profile')
    else:
        form = ProfileForm(instance=request.user)

    return render(request, 'accounts/profile_editing.html', {'form': form})


@login_required
def profile_settings_view(request):
    """Let a signed-in user change their own password."""
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            user = form.save()
            # Rotating the password invalidates the session hash; refresh it so
            # the user is not logged out by their own password change.
            update_session_auth_hash(request, user)
            messages.success(request, 'Password changed successfully.')
            return redirect('accounts:profile_settings')
    else:
        form = PasswordChangeForm(user=request.user)

    return render(request, 'accounts/profile_settings.html', {'form': form})
