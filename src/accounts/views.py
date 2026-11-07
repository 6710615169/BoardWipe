import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from . import game_api
from .forms import (
    BoardgameCreateForm, BoardgameSearchForm, ProfileBoardgameEditForm, ProfileForm,
    RegisterForm, normalize_game_name,
)
from .models import Boardgame, FriendRequest, ProfileBoardgame, User

logger = logging.getLogger(__name__)

CATALOG_PAGE_SIZE = 24

@login_required
def profile_search_view(request):
    q = request.GET.get('q', '').strip()
    genre = request.GET.get('genre', '')
    known = request.GET.get('known', '').strip()
    favorite = request.GET.get('favorite', '').strip()
    owned = request.GET.get('owned', '').strip()

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
        users = users.filter(
            profile_boardgames__is_known=True,
            profile_boardgames__name__icontains=known,
        )
    if favorite:
        users = users.filter(favorite_boardgame__icontains=favorite)
    if owned:
        users = users.filter(
            profile_boardgames__is_owned=True,
            profile_boardgames__name__icontains=owned,
        )

    users = users.distinct().order_by('username').prefetch_related('profile_boardgames')

    return render(request, 'accounts/profile_search.html', {
        'users_found': users,
        'genre_choices': User.GENRE_CHOICES,
        'q': q, 'genre': genre, 'known': known, 'favorite': favorite, 'owned': owned,
    })


@login_required
def profile_detail_view(request, username):
    profile_user = get_object_or_404(User, username=username, is_active=True)
    return render(request, 'accounts/profile_detail.html', {
        'profile_user': profile_user,
        'profile_boardgames': profile_user.profile_boardgames.select_related('boardgame'),
    })

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
        'profile_boardgames': user.profile_boardgames.select_related('boardgame'),
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

    context = {
        'form': form,
        'profile_boardgames': request.user.profile_boardgames.select_related('boardgame'),
    }
    return render(request, 'accounts/profile_editing.html', context)


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


@login_required
def friends_view(request):
    """List the user's friends and their pending friend requests."""
    context = {
        'friends': request.user.friends.all(),
        'incoming_requests': request.user.received_friend_requests.select_related('from_user'),
        'outgoing_requests': request.user.sent_friend_requests.select_related('to_user'),
    }
    return render(request, 'accounts/friends.html', context)


@login_required
@require_POST
def send_friend_request(request, username):
    other = get_object_or_404(User, username=username)

    if other == request.user:
        messages.error(request, 'You cannot add yourself as a friend.')
    elif request.user.friends.filter(pk=other.pk).exists():
        messages.info(request, f'You are already friends with {other.get_display_name()}.')
    elif FriendRequest.objects.filter(from_user=other, to_user=request.user).delete()[0]:
        # They already asked us, so sending one back accepts it.
        request.user.friends.add(other)
        messages.success(request, f'You are now friends with {other.get_display_name()}.')
    else:
        FriendRequest.objects.get_or_create(from_user=request.user, to_user=other)
        messages.success(request, f'Friend request sent to {other.get_display_name()}.')

    return redirect('accounts:friends')


@login_required
@require_POST
def accept_friend_request(request, username):
    # Scoping by to_user means only the recipient can accept.
    friend_request = get_object_or_404(
        FriendRequest, from_user__username=username, to_user=request.user
    )
    request.user.friends.add(friend_request.from_user)
    friend_request.delete()
    messages.success(request, f'You are now friends with {friend_request.from_user.get_display_name()}.')
    return redirect('accounts:friends')


@login_required
@require_POST
def decline_friend_request(request, username):
    friend_request = get_object_or_404(
        FriendRequest, from_user__username=username, to_user=request.user
    )
    friend_request.delete()
    messages.success(request, 'Friend request declined.')
    return redirect('accounts:friends')
  
@login_required
@require_GET
def boardgame_add_view(request):
    """
    Pick a game for the profile from the catalog: search, filter by genre and
    player count, and sort by rating. Each card's + button adds that game.

    Games come from Wikidata (searched live, see game_api.py) and from games
    other players added with "Add new".
    """
    form = BoardgameSearchForm(request.GET)
    query = form.cleaned_data.get('q', '').strip() if form.is_valid() else ''

    found_ids = []
    api_unavailable = False
    if game_api.is_enabled():
        try:
            found_ids = game_api.load_games(query)
        except game_api.GameAPIError:
            logger.warning('Wikidata lookup failed for %r', query, exc_info=True)
            api_unavailable = True

    games = Boardgame.objects.all()
    if query:
        # Wikidata also matches alternate titles a plain name search would miss.
        games = games.filter(Q(name__icontains=query) | Q(external_id__in=found_ids))
    games = form.filter_and_sort(games)

    page = Paginator(games, CATALOG_PAGE_SIZE).get_page(request.GET.get('page'))
    # Mark games already on the profile, matched by link or by name, so their
    # + button can show "Added" instead.
    mine = request.user.profile_boardgames.values_list('boardgame_id', 'name')
    my_ids = {game_id for game_id, _ in mine if game_id}
    my_names = {name.casefold() for _, name in mine}
    for game in page:
        game.is_added = game.pk in my_ids or game.name.casefold() in my_names

    context = {
        'form': form,
        'page': page,
        'api_enabled': game_api.is_enabled(),
        'api_unavailable': api_unavailable,
    }
    return render(request, 'accounts/boardgame_add.html', context)


@login_required
@require_POST
def boardgame_pick_view(request, pk):
    """The + button: add a catalog game to the user's profile as a known game."""
    game = get_object_or_404(Boardgame, pk=pk)
    name = normalize_game_name(game.name)

    if request.user.profile_boardgames.filter(name__iexact=name).exists():
        messages.info(request, f'{game.name} is already on your profile.')
    else:
        try:
            with transaction.atomic():
                ProfileBoardgame.objects.create(user=request.user, name=name, boardgame=game, is_known=True)
        except IntegrityError:
            # A double-click raced past the check above; the game is there either way.
            messages.info(request, f'{game.name} is already on your profile.')
        else:
            messages.success(request, f'{game.name} was added to your profile.')

    # Return to the same search results so several games can be added in a row.
    next_url = request.POST.get('next', '')
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return redirect(next_url)
    return redirect('accounts:boardgame_add')


@login_required
def boardgame_create_view(request):
    """"Add new": create a game that is not in the catalog and put it on the profile."""
    if request.method == 'POST':
        form = BoardgameCreateForm(request.POST, request.FILES, user=request.user)
        if form.is_valid():
            game = form.save()
            messages.success(request, f'{game.name} was added to your profile.')
            return redirect('accounts:profile_editing')
    else:
        form = BoardgameCreateForm(user=request.user)

    return render(request, 'accounts/boardgame_create.html', {'form': form})


@login_required
def boardgame_edit_view(request, pk):
    """Change the picture or known/owned flags of one of the user's own games."""
    # Filtering on user turns someone else's game into a 404, not a 403, so
    # the URL does not reveal which ids exist.
    game = get_object_or_404(ProfileBoardgame, pk=pk, user=request.user)

    if request.method == 'POST':
        form = ProfileBoardgameEditForm(request.POST, request.FILES, instance=game)
        if form.is_valid():
            form.save()
            messages.success(request, f'{game.name} was updated.')
            return redirect('accounts:profile_editing')
    else:
        form = ProfileBoardgameEditForm(instance=game)

    return render(request, 'accounts/boardgame_edit.html', {'form': form, 'game': game})


@login_required
@require_POST
def remove_friend(request, username):
    other = get_object_or_404(User, username=username)
    request.user.friends.remove(other)
    messages.success(request, f'{other.get_display_name()} was removed from your friends.')
    return redirect('accounts:friends')
  
  
@login_required
@require_POST
def boardgame_delete_view(request, pk):
    """POST-only removal of one of the user's games, along with its picture file."""
    game = get_object_or_404(ProfileBoardgame, pk=pk, user=request.user)
    game.picture.delete(save=False)
    game.delete()
    messages.success(request, f'{game.name} was removed from your profile.')
    return redirect('accounts:profile_editing')
