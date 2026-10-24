from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('profile/', views.profile_view, name='profile'),
    path('profile/settings/', views.profile_settings_view, name='profile_settings'),
    path('profile/friends/', views.friends_view, name='friends'),
    path('profile/friends/request/<str:username>/', views.send_friend_request, name='send_friend_request'),
    path('profile/friends/accept/<str:username>/', views.accept_friend_request, name='accept_friend_request'),
    path('profile/friends/decline/<str:username>/', views.decline_friend_request, name='decline_friend_request'),
    path('profile/friends/remove/<str:username>/', views.remove_friend, name='remove_friend'),
]
