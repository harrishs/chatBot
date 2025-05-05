from django.db import models
from django.contrib.auth.models import AbstractUser

class Company(models.Model):
    name = models.CharField(max_length=255)
    website = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name
    

class User(AbstractUser):
    company = models.ForeignKey('Company', on_delete=models.CASCADE, related_name='users', null=True)

    def __str__(self):
        company_name = self.company.name if self.company else "No Company"
        return f"{self.email} ({company_name})"


class ChatBotInstance(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='chatBots')
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.company.name})"
    

class JiraSync(models.Model):
    chatBot = models.ForeignKey(ChatBotInstance, on_delete=models.CASCADE, related_name='jiraSyncs')
    board_url = models.URLField()
    last_sync_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Jira Sync for {self.chatBot.name} ({self.chatBot.company.name})"
    

class ConfluenceSync(models.Model):
    chatBot = models.ForeignKey(ChatBotInstance, on_delete=models.CASCADE, related_name='confluenceSyncs')
    space_url = models.URLField()
    last_sync_time = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Confluence Sync for {self.chatBot.name} ({self.chatBot.company.name})"
    

class ChatFeedback(models.Model):
    chatBot = models.ForeignKey(ChatBotInstance, on_delete=models.CASCADE, related_name='feedbacks')
    question = models.TextField()
    answer = models.TextField()
    is_helpful = models.BooleanField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Feedback for {self.chatBot.name} ({self.chatBot.company.name}) - Helpful: {self.is_helpful}"

