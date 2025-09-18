from django.db import models
from django.contrib.auth.models import AbstractUser
from chat.encryption import fernet
from pgvector.django import VectorField

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
    
    
class Credential(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='credentials')
    name = models.CharField(max_length=100)
    email = models.EmailField()
    _api_key = models.CharField(max_length=512)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.company.name})"
    

    @property
    def api_key(self):
        f = fernet
        return f.decrypt(self._api_key.encode()).decode()
    
    @api_key.setter
    def api_key(self, raw_key):
        f = fernet
        self._api_key = f.encrypt(raw_key.encode()).decode()


class JiraSync(models.Model):
    chatBot = models.ForeignKey(ChatBotInstance, on_delete=models.CASCADE, related_name='jiraSyncs')
    board_url = models.URLField()
    credential = models.ForeignKey(Credential, on_delete=models.CASCADE, null=True, blank=True)
    last_sync_time = models.DateTimeField(null=True, blank=True)
    SYNC_INTERVAL_CHOICES = [
        ('manual', 'Manual'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]
    sync_interval = models.CharField(max_length=10, choices=SYNC_INTERVAL_CHOICES, default='manual')

    def __str__(self):
        return f"Jira Sync for {self.chatBot.name} ({self.chatBot.company.name})"
    

class ConfluenceSync(models.Model):
    chatBot = models.ForeignKey(ChatBotInstance, on_delete=models.CASCADE, related_name='confluenceSyncs')
    space_url = models.URLField()
    credential = models.ForeignKey(Credential, on_delete=models.CASCADE, null=True, blank=True)
    last_sync_time = models.DateTimeField(null=True, blank=True)
    SYNC_INTERVAL_CHOICES = [
        ('manual', 'Manual'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]
    sync_interval = models.CharField(max_length=10, choices=SYNC_INTERVAL_CHOICES, default='manual')

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

class JiraIssue(models.Model):
    sync = models.ForeignKey(JiraSync, on_delete=models.CASCADE, related_name='issues')
    issue_key = models.CharField(max_length=100)
    summary = models.TextField()
    description = models.TextField(null=True, blank=True)
    status = models.CharField(max_length=100)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    def __str__(self):
        return f"{self.issue_key} - {self.summary}"
    
class JiraComment(models.Model):
    issue = models.ForeignKey(JiraIssue, on_delete=models.CASCADE, related_name='comments')
    author = models.CharField(max_length=255)
    content = models.TextField()
    created_at = models.DateTimeField()

    def __str__(self):
        return f"Comment by {self.author} on {self.issue.issue_key}"
    
class ConfluencePage(models.Model):
    sync = models.ForeignKey(ConfluenceSync, on_delete=models.CASCADE, related_name='pages')
    title = models.CharField(max_length=255)
    content = models.TextField()
    url = models.URLField()
    last_updated = models.DateTimeField()

    def __str__(self):
        return f"{self.title}"

class GitCredential(models.Model):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name='gitCredentials')
    name = models.CharField(max_length=255)
    github_username = models.CharField(max_length=255)
    _token = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.github_username})"
    
    @property
    def token(self):
        from chat.encryption import fernet
        return fernet.decrypt(self._token.encode()).decode()

    @token.setter
    def token(self, raw_token: str):
        from chat.encryption import fernet
        self._token = fernet.encrypt(raw_token.encode()).decode()
    
class GitRepoSync(models.Model):
    chatBot = models.ForeignKey(ChatBotInstance, on_delete=models.CASCADE, related_name='gitRepoSyncs')
    credential = models.ForeignKey(GitCredential, on_delete=models.PROTECT, related_name='repoSyncs')
    repo_full_name = models.CharField(max_length=300)
    branch = models.CharField(max_length=100, default='main')
    last_sync_time = models.DateTimeField(null=True, blank=True)
    SYNC_INTERVAL_CHOICES = [
        ('manual', 'Manual'),
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ]
    sync_interval = models.CharField(max_length=10, choices=SYNC_INTERVAL_CHOICES, default='manual')

    def __str__(self):
        return f"{self.repo_full_name}@{self.branch} ({self.chatBot.name})"
    
class GitRepoFile(models.Model):
    sync = models.ForeignKey(GitRepoSync, on_delete=models.CASCADE, related_name='files')
    path = models.CharField(max_length=2000)
    sha = models.CharField(max_length=100)
    size = models.IntegerField()
    url = models.URLField()
    content = models.TextField()
    last_updated = models.DateTimeField()

    class Meta:
        unique_together = ('sync', 'path')

    def __str__(self):
        return f"{self.path} ({self.sync.repo_full_name})"

class Document(models.Model):
    SOURCE_CHOICES = [
        ('jira', 'Jira'),
        ('confluence', 'Confluence'),
        ('github', 'GitHub'),
    ]

    company = models.ForeignKey("chat.Company", on_delete=models.CASCADE)
    chatbot = models.ForeignKey("chat.ChatBotInstance", on_delete=models.CASCADE)
    source = models.CharField(max_length=50, choices=SOURCE_CHOICES)
    source_id = models.CharField(max_length=200)
    content = models.TextField()
    embedding = VectorField(dimensions=1536)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("company", "source", "source_id")

    def __str__(self):
        return f"Document {self.id} from {self.source} ({self.company.name})"