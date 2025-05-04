from django.contrib import admin
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback

admin.site.register(Company)
admin.site.register(ChatBotInstance)
admin.site.register(JiraSync)
admin.site.register(ConfluenceSync)
admin.site.register(ChatFeedback)
