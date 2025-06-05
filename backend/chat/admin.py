from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback, Credential, JiraComment, JiraIssue

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = BaseUserAdmin.fieldsets + (
        ("Company Info", {"fields": ("company",)}),
    )

admin.site.register(Company)
admin.site.register(ChatBotInstance)
admin.site.register(JiraSync)
admin.site.register(ConfluenceSync)
admin.site.register(ChatFeedback)
admin.site.register(Credential)
admin.site.register(JiraIssue)
admin.site.register(JiraComment)
