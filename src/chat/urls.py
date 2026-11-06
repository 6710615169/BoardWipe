from django.urls import path

from . import views

app_name = 'chat'

urlpatterns = [
    path('<str:username>/', views.conversation_view, name='conversation'),
    path('<str:username>/after/<int:after_id>/', views.new_messages_view, name='new_messages'),
]
