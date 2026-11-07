from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Boardgame, FriendRequest, ProfileBoardgame, User

admin.site.register(User, UserAdmin)
admin.site.register(FriendRequest)
admin.site.register(ProfileBoardgame)


@admin.register(Boardgame)
class BoardgameAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "rating",
        "min_players",
        "max_players",
        "genres",
        "external_id",
        "created_by",
    )
    search_fields = ("name",)
