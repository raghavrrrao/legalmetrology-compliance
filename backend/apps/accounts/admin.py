from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone

from apps.accounts.models import ApiToken, User

admin.site.register(User, UserAdmin)


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    """Issued tokens, for an operator who needs to cut one off - a lost phone.

    Read-only apart from revocation. Tokens are issued only by logging in, and
    the stored hash is not shown: it is not the token, but nothing is gained by
    displaying it, and every copy of it is one more place it could be read.
    """

    list_display = ("id", "user", "created_at", "expires_at", "revoked_at", "last_used_at")
    list_filter = ("revoked_at", "expires_at")
    search_fields = ("user__username",)
    fields = ("user", "created_at", "expires_at", "revoked_at", "last_used_at")
    readonly_fields = fields
    actions = ["revoke_selected"]

    def has_add_permission(self, request) -> bool:
        return False

    @admin.action(description="Revoke selected tokens")
    def revoke_selected(self, request, queryset):
        now = timezone.now()
        count = queryset.filter(revoked_at__isnull=True).update(revoked_at=now, updated_at=now)
        self.message_user(request, f"Revoked {count} token(s).")
