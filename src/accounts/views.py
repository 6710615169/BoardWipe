from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import ProfileForm, RegisterForm


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
            next_url = request.POST.get('next')
            if next_url and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
            ):
                return redirect(next_url)
            return redirect(settings.LOGIN_REDIRECT_URL)
        # The form already renders "Please enter a correct username and
        # password", so adding a messages.error here would show it twice.
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
