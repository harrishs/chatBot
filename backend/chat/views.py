from django.shortcuts import get_object_or_404
from rest_framework import viewsets, permissions, status
from rest_framework.authentication import SessionAuthentication
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback, Credential, GitCredential, GitRepoSync, GitRepoFile
from .serializers import CompanySerializer, ChatBotInstanceSerializer, JiraSyncSerializer, ConfluenceSyncSerializer, ChatFeedbackSerializer, UserSerializer, CredentialSerializer, GitCredentialSerializer, GitCredentialSummarySerializer, GitRepoSyncSerializer, GitRepoFileSerializer
from django.contrib.auth import get_user_model
import logging
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError, NotFound
from rest_framework.decorators import action, api_view
from rest_framework.views import APIView
from chat.utils.jira import fetch_jira_issues, ingest_jira_issue
from chat.utils.confluence import fetch_confluence_pages, ingest_confluence_pages
from chat.utils.github import run_github_sync
from chat.utils.embeddings import search_documents
from chat.utils.rag import generate_answer
from django.contrib.auth import authenticate, login, logout
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect


logger = logging.getLogger(__name__)


User = get_user_model()


class IsAdminOrReadOnly(permissions.BasePermission):
    """Allow non-admin users to perform read-only requests."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated
        return bool(request.user and request.user.is_staff)


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return User.objects.filter(company=self.request.user.company)

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)


@method_decorator(csrf_protect, name='dispatch')
class LoginView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = [SessionAuthentication]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')

        if not username or not password:
            return Response({'detail': 'Username and password are required.'}, status=status.HTTP_400_BAD_REQUEST)

        user = authenticate(request, username=username, password=password)

        if not user:
            return Response({'detail': 'Invalid credentials.'}, status=status.HTTP_400_BAD_REQUEST)

        login(request, user)
        serializer = UserSerializer(user)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        logout(request)
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(
            settings.SESSION_COOKIE_NAME,
            samesite=getattr(settings, 'SESSION_COOKIE_SAMESITE', 'Lax'),
            domain=getattr(settings, 'SESSION_COOKIE_DOMAIN', None),
        )
        return response


class SessionView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        if not request.user or not request.user.is_authenticated:
            return Response(
                {'detail': 'Authentication credentials were not provided.'},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        serializer = UserSerializer(request.user)
        return Response(serializer.data, status=status.HTTP_200_OK)


@method_decorator(ensure_csrf_cookie, name='dispatch')
class CSRFTokenView(APIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []

    def get(self, request):
        return Response({'detail': 'CSRF cookie set.'}, status=status.HTTP_200_OK)

class CompanyViewSet(viewsets.ModelViewSet):
    serializer_class = CompanySerializer
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Company.objects.none()

        if user.is_staff or user.is_superuser:
            return Company.objects.all()

        if user.company_id:
            return Company.objects.filter(id=user.company_id)

        return Company.objects.none()

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

    def _validate_credential(self, credential):
        if credential and credential.company != self.request.user.company:
            raise PermissionDenied("You cannot use credentials for a different company")

    def _validate_request_credential_id(self, data):
        credential_id = data.get('credential_id') or data.get('credential')
        if not credential_id:
            return
        try:
            credential = Credential.objects.get(pk=credential_id)
        except Credential.DoesNotExist:
            return
        self._validate_credential(credential)

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

        self._validate_request_credential_id(request.data)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        self._validate_credential(serializer.validated_data.get('credential'))
        sync = serializer.save(chatBot=chatBot)
        response_serializer = self.get_serializer(sync)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        self._validate_request_credential_id(request.data)
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        self._validate_credential(serializer.validated_data.get('credential'))
        if serializer.instance.chatBot.company != self.request.user.company:
            raise PermissionDenied("You cannot modify a sync outside your company")
        serializer.save()
    
    @action(detail=True, methods=['post'])
    def sync_now(self, request, chatbot_pk=None, pk=None):
        sync = self.get_object()
        try:
            issues_with_comments = fetch_jira_issues(sync)
            documents_created = 0
            for issue, comments in issues_with_comments:
                docs = ingest_jira_issue(
                    company=sync.chatBot.company,
                    chatbot=sync.chatBot,
                    issue=issue,
                    comments=comments,
                )
                documents_created += len(docs)
        except Exception:
            logger.exception("Failed to sync Jira for sync %s", sync.pk)
            return Response(
                {"detail": "Failed to sync Jira."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "status": f"Jira sync completed, {len(issues_with_comments)} issues processed.",
                "documents_ingested": documents_created,
            },
            status=status.HTTP_200_OK,
        )

class ConfluenceSyncViewSet(viewsets.ModelViewSet):
    serializer_class = ConfluenceSyncSerializer
    permission_classes = [permissions.IsAuthenticated]

    def _validate_credential(self, credential):
        if credential and credential.company != self.request.user.company:
            raise PermissionDenied("You cannot use credentials for a different company")

    def _validate_request_credential_id(self, data):
        credential_id = data.get('credential_id') or data.get('credential')
        if not credential_id:
            return
        try:
            credential = Credential.objects.get(pk=credential_id)
        except Credential.DoesNotExist:
            return
        self._validate_credential(credential)

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

        self._validate_request_credential_id(request.data)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        self._validate_credential(serializer.validated_data.get('credential'))
        sync = serializer.save(chatBot=chatBot)
        response_serializer = self.get_serializer(sync)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        self._validate_request_credential_id(request.data)
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        self._validate_credential(serializer.validated_data.get('credential'))
        if serializer.instance.chatBot.company != self.request.user.company:
            raise PermissionDenied("You cannot modify a sync outside your company")
        serializer.save()
    
    @action(detail=True, methods=['post'])
    def sync_now(self, request, chatbot_pk=None, pk=None):
        sync = self.get_object()
        try:
            pages = fetch_confluence_pages(sync)
            documents_created = ingest_confluence_pages(sync, pages=pages)
        except Exception:
            logger.exception("Failed to sync Confluence for sync %s", sync.pk)
            return Response(
                {"detail": "Failed to sync Confluence."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "status": f"Confluence sync completed, {len(pages)} pages processed.",
                "documents_ingested": documents_created,
            },
            status=status.HTTP_200_OK,
        )

class ChatFeedbackViewSet(viewsets.ModelViewSet):
    serializer_class = ChatFeedbackSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ChatFeedback.objects.filter(chatBot__company=self.request.user.company)

    def _get_chatbot_from_request(self):
        request = self.request
        chat_bot_id = (
            request.data.get('chatBot')
            or request.data.get('chatbot')
            or request.query_params.get('chatBot')
            or request.query_params.get('chatbot')
        )

        if not chat_bot_id:
            raise ValidationError({'chatBot': ['This field is required.']})

        try:
            return ChatBotInstance.objects.get(pk=chat_bot_id)
        except ChatBotInstance.DoesNotExist:
            raise NotFound('Chatbot not found.')

    def create(self, request, *args, **kwargs):
        chatBot = self._get_chatbot_from_request()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer, chatBot=chatBot)
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer, chatBot=None):
        chatBot = chatBot or self._get_chatbot_from_request()
        if chatBot.company != self.request.user.company:
            raise PermissionDenied("You cannot create feedback for a chatbot outside your company")
        serializer.save(chatBot=chatBot)

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
        
        try:
            files_processed, documents_ingested = run_github_sync(sync)
        except Exception:
            logger.exception("Failed to sync GitHub for sync %s", sync.pk)
            return Response(
                {"detail": "Failed to sync GitHub."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "status": f"GitHub sync completed, {files_processed} files processed.",
                "documents_ingested": documents_ingested,
            },
            status=status.HTTP_200_OK,
        )
    
@api_view(['POST'])
def query_documents(request, chatbot_id):
    """
    Query embeddings for Jira, Confluence, and GitHub docs.

    Example POST:
    {
        "query": "How do I deploy the app with Docker?",
        "top_k": 5
    }
    """
    query = request.data.get("query")
    company_id = request.user.company_id
    top_k = int(request.data.get("top_k", 5))
    if not query:
        return Response({"error": "Missing 'query' in request body"}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        results = search_documents(company_id, chatbot_id, query, top_k)
        return Response(results)
    except Exception as e:
        logger.error(f"Error querying documents: {e}")
        return Response({"error": "Failed to query documents"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
def chat_with_bot(request, chatbot_id):
    """
    Chat endpoint using RAG.

    Example POST:
    {
        "query": "How do I deploy the app with Docker?"
    }
    """
    query = request.data.get("query")
    company_id = request.user.company_id
    if not query:
        return Response({"error": "Missing 'query' in request body"}, status=status.HTTP_400_BAD_REQUEST)
    
    try:
        response = generate_answer(company_id, chatbot_id, query, top_k=5)
        return Response(response)
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        return Response({"error": "Failed to generate answer"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)