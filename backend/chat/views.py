from django.shortcuts import get_object_or_404
from rest_framework import viewsets, permissions, status
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback, Credential, GitCredential, GitRepoSync, GitRepoFile
from .serializers import CompanySerializer, ChatBotInstanceSerializer, JiraSyncSerializer, ConfluenceSyncSerializer, ChatFeedbackSerializer, UserSerializer, CredentialSerializer, GitCredentialSerializer, GitCredentialSummarySerializer, GitRepoSyncSerializer, GitRepoFileSerializer
from django.contrib.auth import get_user_model
import logging
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import action, api_view
from chat.utils.jira import fetch_jira_issues
from chat.utils.confluence import fetch_confluence_pages
from chat.utils.github import run_github_sync
from chat.utils.embeddings import search_documents


logger = logging.getLogger(__name__)


User = get_user_model()

class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(company=self.request.user.company)
    
    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)

class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer

class CredentialViewSet(viewsets.ModelViewSet):
    serializer_class = CredentialSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Credential.objects.filter(company=self.request.user.company)
    
    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)

    def perform_update(self, serializer):
        if serializer.instance.company != self.request.user.company:
            raise PermissionDenied("You cannot update credentials for a different company's credentials")
        serializer.save()

    def perform_destroy(self, instance):
        if instance.company != self.request.user.company:
            raise PermissionDenied("You cannot delete credentials for a different company's credentials")
        instance.delete()

class ChatBotInstanceViewSet(viewsets.ModelViewSet):
    serializer_class = ChatBotInstanceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ChatBotInstance.objects.filter(company=self.request.user.company)
    
    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)

class JiraSyncViewSet(viewsets.ModelViewSet):
    serializer_class = JiraSyncSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = 'id'
    lookup_url_kwarg = 'pk'

    def get_queryset(self):
        chatbot_id = self.kwargs['chatbot_pk']
        if not chatbot_id:
            raise PermissionDenied("Missing 'chatbot_id' in URL path.")
        return JiraSync.objects.filter(chatBot__id=chatbot_id, chatBot__company=self.request.user.company)
    
    def create(self, request, *args, **kwargs):
        # Attach the chatbot manually since it's passed through the URL
        chatbot_id = self.kwargs['chatbot_pk']

        try:
            chatBot = ChatBotInstance.objects.get(id=chatbot_id, company=request.user.company)
        except ChatBotInstance.DoesNotExist:
            raise PermissionDenied("Invalid chatbot or not in your company")

        # Include the chatbot in the validated data
        mutable_data = request.data.copy()
        mutable_data['chatBot'] = chatBot.id

        serializer = self.get_serializer(data=mutable_data)

        if not serializer.is_valid():
            logger.error("Validation error: %s", serializer.errors)
            return Response(serializer.errors, status=400)

        serializer.save(chatBot=chatBot)
        return Response(serializer.data, status=201)
    
    @action(detail=True, methods=['post'])
    def sync_now(self, request, chatbot_pk=None, pk=None):
        sync = self.get_object()
        fetch_jira_issues(sync)
        return Response({"status": "Jira sync initiated"}, status=status.HTTP_200_OK)

class ConfluenceSyncViewSet(viewsets.ModelViewSet):
    serializer_class = ConfluenceSyncSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        chatbot_id = self.kwargs['chatbot_pk']
        if not chatbot_id:
            raise PermissionDenied("Missing 'chatbot_id' in URL path.")
        return ConfluenceSync.objects.filter(chatBot__id=chatbot_id, chatBot__company=self.request.user.company)
    
    def create(self, request, *args, **kwargs):
        chatbot_id = self.kwargs['chatbot_pk']

        try:
            chatBot = ChatBotInstance.objects.get(
                id=chatbot_id,
                company=request.user.company
            )
        except ChatBotInstance.DoesNotExist:
            raise PermissionDenied("Invalid chatbot or not in your company")

        # Inject chatBot into the data explicitly
        mutable_data = request.data.copy()
        mutable_data['chatBot'] = chatBot.id

        serializer = self.get_serializer(data=mutable_data)

        if not serializer.is_valid():
            logger.error("ConfluenceSync Validation Error: %s", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save(chatBot=chatBot)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'])
    def sync_now(self, request, chatbot_pk=None, pk=None):
        sync = self.get_object()
        fetch_confluence_pages(sync)
        return Response({"status": "Confluence sync initiated"}, status=status.HTTP_200_OK)

class ChatFeedbackViewSet(viewsets.ModelViewSet):
    serializer_class = ChatFeedbackSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ChatFeedback.objects.filter(chatBot__company=self.request.user.company)
    
    def perform_create(self, serializer):
        chatBot = serializer.validated_data['chatBot']
        if chatBot.company != self.request.user.company:
            raise PermissionError("You cannot create feedback for a chatbot outside your company")
        serializer.save()

class GitCredentialViewSet(viewsets.ModelViewSet):
    serializer_class = GitCredentialSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return GitCredential.objects.filter(company=self.request.user.company)
    
    def perform_destroy(self, instance):
        if instance.company != self.request.user.company:
            raise PermissionDenied("You cannot delete git credentials for a different company")
        return super().perform_destroy(instance)
    
class GitRepoSyncViewSet(viewsets.ModelViewSet):
    serializer_class = GitRepoSyncSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_chatbot(self):
        chatbot_id = self.kwargs['chatbot_pk']
        return get_object_or_404(ChatBotInstance, id=chatbot_id, company=self.request.user.company)
    
    def get_queryset(self):
        chatbot_id = self.kwargs['chatbot_pk']
        qs = GitRepoSync.objects.filter(chatBot__company=self.request.user.company)
        if chatbot_id:
            qs = qs.filter(chatBot__id=chatbot_id)
        return qs
    
    def create(self, request, *args, **kwargs):
        chatbot = self.get_chatbot()
        data = request.data.copy()
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        obj = serializer.save(chatBot=chatbot)
        return Response(self.get_serializer(obj).data, status=status.HTTP_201_CREATED)
    
    @action(detail=True, methods=['post'])
    def sync_now(self, request, chatbot_pk=None, pk=None):
        sync = self.get_object()
        if sync.chatBot.company != request.user.company:
            raise PermissionDenied("You cannot sync a repo for a chatbot outside your company")
        
        count = run_github_sync(sync)
        return Response({"status": f"GitHub sync completed, {count} files processed."}, status=status.HTTP_200_OK)
    
@api_view(['POST'])
def query_documents(request, company_id):
    """
    Query embeddings for Jira, Confluence, and GitHub docs.

    Example POST:
    {
        "query": "How do I deploy the app with Docker?",
        "top_k": 5
    }
    """
    query = request.data.get("query")
    top_k = int(request.data.get("top_k", 5))
    results = search_documents(company_id, query, top_k)
    return Response(results)