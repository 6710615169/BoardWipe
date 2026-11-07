from django.contrib import admin
from .models import ConversationNotification, Message

admin.site.register(Message)
admin.site.register(ConversationNotification)
