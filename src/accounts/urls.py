from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('profile-settings/', views.profile_settings_view, name='profile_settings'),
    path('profile/', views.profile_placeholder_view, name='profile'),
]