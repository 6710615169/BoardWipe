from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/edit/', views.profile_editing_view, name='profile_editing'),
    path('profile/settings/', views.profile_settings_view, name='profile_settings'),
    path('profile/friends/', views.friends_view, name='friends'),
    path('profile/friends/request/<str:username>/', views.send_friend_request, name='send_friend_request'),
    path('profile/friends/accept/<str:username>/', views.accept_friend_request, name='accept_friend_request'),
    path('profile/friends/decline/<str:username>/', views.decline_friend_request, name='decline_friend_request'),
    path('profile/friends/remove/<str:username>/', views.remove_friend, name='remove_friend'),

    path('search/', views.profile_search_view, name='profile_search'),
    path('users/<str:username>/', views.profile_detail_view, name='profile_detail'),

    path('profile/boardgames/add/', views.boardgame_add_view, name='boardgame_add'),
    path('profile/boardgames/<int:pk>/edit/', views.boardgame_edit_view, name='boardgame_edit'),
    path('profile/boardgames/<int:pk>/delete/', views.boardgame_delete_view, name='boardgame_delete'),

]
