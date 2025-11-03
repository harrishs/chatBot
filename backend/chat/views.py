from django.shortcuts import get_object_or_404
from rest_framework import viewsets, permissions, status
from rest_framework.authentication import SessionAuthentication
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback, Credential, GitCredential, GitRepoSync, GitRepoFile, SyncJob, SyncStatusMixin
from .serializers import CompanySerializer, ChatBotInstanceSerializer, JiraSyncSerializer, ConfluenceSyncSerializer, ChatFeedbackSerializer, UserSerializer, CredentialSerializer, GitCredentialSerializer, GitCredentialSummarySerializer, GitRepoSyncSerializer, GitRepoFileSerializer
from django.contrib.auth import get_user_model
import logging
import re
from django.db import transaction
from rest_framework.response import Response
from rest_framework.exceptions import (
    NotAuthenticated,
    PermissionDenied,
    ValidationError,
    NotFound,
)
from rest_framework.decorators import action, api_view
from rest_framework.views import APIView
from chat.utils.embeddings import (
    delete_feedback_document,
    search_documents,
    upsert_feedback_document,
)
from chat.utils.rag import generate_answer
from django.contrib.auth import authenticate, login, logout
from django.http import Http404
from django.conf import settings
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect


logger = logging.getLogger(__name__)


ACTIVE_SYNC_STATUSES = (
    SyncStatusMixin.Status.QUEUED,
    SyncStatusMixin.Status.RUNNING,
)


DEFAULT_CHAT_TOP_K = 5
ENUMERATION_TOP_K = 15
MAX_CHAT_TOP_K = 25
_ENUMERATION_TOKENS = {"all", "list", "every", "everything", "entire", "complete"}
_ENUMERATION_PHRASES = ("full list", "entire list", "complete list")


def _build_sync_status_response(sync):
    job_id = getattr(sync, 'current_job_id', None)
    job_status = None
    job_message = None
    if job_id:
        try:
            job_obj = SyncJob.objects.get(pk=int(job_id))
        except (ValueError, SyncJob.DoesNotExist):
            job_obj = None
        if job_obj:
            job_status = job_obj.status
            job_message = job_obj.status_message

    return {
        'job_id': job_id,
        'status': sync.sync_status,
        'message': sync.sync_status_message,
        'last_sync_time': sync.last_sync_time,
        'job_status': job_status,
        'job_message': job_message,
    }


def _has_active_sync_job(sync):
    if sync.sync_status in ACTIVE_SYNC_STATUSES:
        return True

    job_id = getattr(sync, 'current_job_id', None)
    if not job_id:
        return False

    try:
        job = SyncJob.objects.get(pk=int(job_id))
    except (ValueError, SyncJob.DoesNotExist):
        return False

    return job.status in ACTIVE_SYNC_STATUSES


User = get_user_model()


class IsAdminOrReadOnly(permissions.BasePermission):
    """Allow non-admin users to perform read-only requests."""

    def _is_admin_user(self, user):
        return bool(user and user.is_authenticated and user.is_staff)

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            if request.user and request.user.is_authenticated:
                return True
            raise NotAuthenticated()

        if not request.user or not request.user.is_authenticated:
            raise NotAuthenticated()

        if getattr(view, "basename", None) == "user":
            if request.method == "POST" or getattr(view, "action", None) == "create":
                return self._is_admin_user(request.user)

            return bool(request.user and request.user.is_authenticated)

        return self._is_admin_user(request.user)

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return request.user and request.user.is_authenticated

        if isinstance(obj, User) and request.user == obj:
            return True

        return self._is_admin_user(request.user)


class IsCompanyAdminOrReadOnly(IsAdminOrReadOnly):
    """Allow company admins (non-staff) to perform write actions."""

    def _is_admin_user(self, user):
        if not user or not user.is_authenticated:
            return False

        if user.is_staff:
            return True

        return getattr(user, "role", None) == User.Role.ADMIN


class UserViewSet(viewsets.ModelViewSet):
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]

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

        if user.is_superuser:
            return Company.objects.all()

        if user.company_id:
            return Company.objects.filter(id=user.company_id)

        return Company.objects.none()

class CredentialViewSet(viewsets.ModelViewSet):
    serializer_class = CredentialSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]

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
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]

    def get_queryset(self):
        return ChatBotInstance.objects.filter(company=self.request.user.company)

    def perform_create(self, serializer):
        serializer.save(company=self.request.user.company)

    @action(detail=True, methods=['get'], url_path='sync-summary')
    def sync_summary(self, request, pk=None):
        chatbot = self.get_object()

        def serialize_datetime(value):
            if not value:
                return None
            if timezone.is_aware(value):
                value = timezone.localtime(value)
            return value.isoformat()

        def jira_name(sync):
            return getattr(sync, 'board_url', None) or f"Jira sync #{sync.id}"

        def confluence_name(sync):
            return getattr(sync, 'space_url', None) or f"Confluence sync #{sync.id}"

        def git_name(sync):
            repo = getattr(sync, 'repo_full_name', None) or f"Repo sync #{sync.id}"
            branch = getattr(sync, 'branch', None)
            return f"{repo}@{branch}" if branch else repo

        type_definitions = [
            ("jira", "Jira", chatbot.jiraSyncs.all(), jira_name),
            ("confluence", "Confluence", chatbot.confluenceSyncs.all(), confluence_name),
            ("git", "Git Repository", chatbot.gitRepoSyncs.all(), git_name),
        ]

        part_summaries = {}

        for type_key, label, queryset, name_getter in type_definitions:
            syncs = list(queryset)
            statuses = {}
            failing_ids = []
            running_ids = []
            latest_dt = None
            latest_id = None
            latest_name = None
            next_dt = None
            next_id = None
            next_name = None

            for sync in syncs:
                status_value = getattr(sync, 'sync_status', None) or SyncStatusMixin.Status.IDLE
                status_key = str(status_value).lower()
                statuses[status_key] = statuses.get(status_key, 0) + 1

                if status_key == SyncStatusMixin.Status.FAILED:
                    failing_ids.append(sync.id)

                if status_key in (SyncStatusMixin.Status.QUEUED, SyncStatusMixin.Status.RUNNING):
                    running_ids.append(sync.id)

                last_sync_time = getattr(sync, 'last_sync_time', None)
                if last_sync_time and (latest_dt is None or last_sync_time > latest_dt):
                    latest_dt = last_sync_time
                    latest_id = sync.id
                    latest_name = name_getter(sync)

                next_sync_at = getattr(sync, 'next_sync_at', None)
                if next_sync_at and (next_dt is None or next_sync_at < next_dt):
                    next_dt = next_sync_at
                    next_id = sync.id
                    next_name = name_getter(sync)

            part_summaries[type_key] = {
                'type': type_key,
                'label': label,
                'total': len(syncs),
                'failing': len(failing_ids),
                'running': len(running_ids),
                'statuses': statuses,
                'failing_ids': failing_ids,
                'running_ids': running_ids,
                'latest_dt': latest_dt,
                'latest_id': latest_id,
                'latest_name': latest_name,
                'next_dt': next_dt,
                'next_id': next_id,
                'next_name': next_name,
            }

        overall_statuses = {}
        overall_total = 0
        overall_failing = 0
        overall_running = 0
        latest_overall_part = None
        next_overall_part = None

        for part in part_summaries.values():
            overall_total += part['total']
            overall_failing += part['failing']
            overall_running += part['running']
            for status, count in part['statuses'].items():
                overall_statuses[status] = overall_statuses.get(status, 0) + count

            if part['latest_dt'] and (
                latest_overall_part is None or part['latest_dt'] > latest_overall_part['latest_dt']
            ):
                latest_overall_part = part

            if part['next_dt'] and (
                next_overall_part is None or part['next_dt'] < next_overall_part['next_dt']
            ):
                next_overall_part = part

        overall_summary = {
            'total': overall_total,
            'failing': overall_failing,
            'running': overall_running,
            'statuses': overall_statuses,
        }

        if latest_overall_part and latest_overall_part['latest_dt']:
            overall_summary['latest_sync'] = {
                'sync_id': latest_overall_part['latest_id'],
                'occurred_at': serialize_datetime(latest_overall_part['latest_dt']),
                'type': latest_overall_part['type'],
                'type_label': latest_overall_part['label'],
                'name': latest_overall_part['latest_name'],
            }
        else:
            overall_summary['latest_sync'] = None

        if next_overall_part and next_overall_part['next_dt']:
            overall_summary['next_scheduled'] = {
                'sync_id': next_overall_part['next_id'],
                'scheduled_for': serialize_datetime(next_overall_part['next_dt']),
                'type': next_overall_part['type'],
                'type_label': next_overall_part['label'],
                'name': next_overall_part['next_name'],
            }
        else:
            overall_summary['next_scheduled'] = None

        def format_part(part):
            formatted = {
                'type': part['type'],
                'label': part['label'],
                'total': part['total'],
                'failing': part['failing'],
                'running': part['running'],
                'statuses': part['statuses'],
                'failing_ids': part['failing_ids'],
                'running_ids': part['running_ids'],
            }
            if part['latest_dt']:
                formatted['latest_sync'] = {
                    'sync_id': part['latest_id'],
                    'occurred_at': serialize_datetime(part['latest_dt']),
                    'type': part['type'],
                    'type_label': part['label'],
                    'name': part['latest_name'],
                }
            else:
                formatted['latest_sync'] = None

            if part['next_dt']:
                formatted['next_scheduled'] = {
                    'sync_id': part['next_id'],
                    'scheduled_for': serialize_datetime(part['next_dt']),
                    'type': part['type'],
                    'type_label': part['label'],
                    'name': part['next_name'],
                }
            else:
                formatted['next_scheduled'] = None

            return formatted

        response_payload = {
            'overall': overall_summary,
        }

        for type_key, label, _, _ in type_definitions:
            part = part_summaries.get(type_key)
            if part is None:
                response_payload[type_key] = {
                    'type': type_key,
                    'label': label,
                    'total': 0,
                    'failing': 0,
                    'running': 0,
                    'statuses': {},
                    'failing_ids': [],
                    'running_ids': [],
                    'latest_sync': None,
                    'next_scheduled': None,
                }
            else:
                response_payload[type_key] = format_part(part)

        return Response(response_payload, status=status.HTTP_200_OK)

class JiraSyncViewSet(viewsets.ModelViewSet):
    serializer_class = JiraSyncSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]
    lookup_field = 'id'
    lookup_url_kwarg = 'pk'

    def _get_chatbot_pk(self):
        chatbot_id = self.kwargs.get('chatbot_pk')
        if not chatbot_id:
            raise PermissionDenied("Missing 'chatbot_id' in URL path.")
        try:
            return int(chatbot_id)
        except ValueError:
            raise ValidationError({'chatbot': ['A valid integer is required.']})

    def _validate_credential(self, credential):
        if credential and credential.company != self.request.user.company:
            raise NotFound("Credential not found.")

    def _validate_request_credential_id(self, data):
        credential_id = data.get('credential_id') or data.get('credential')
        if not credential_id:
            return
        try:
            credential_pk = int(credential_id)
        except (TypeError, ValueError):
            raise ValidationError({'credential_id': ['A valid integer is required.']})
        try:
            credential = Credential.objects.get(pk=credential_pk)
        except Credential.DoesNotExist:
            return
        self._validate_credential(credential)

    def get_queryset(self):
        chatbot_pk = self._get_chatbot_pk()
        return JiraSync.objects.filter(chatBot__id=chatbot_pk, chatBot__company=self.request.user.company)

    def create(self, request, *args, **kwargs):
        # Attach the chatbot manually since it's passed through the URL
        chatbot_pk = self._get_chatbot_pk()
        chatBot = get_object_or_404(
            ChatBotInstance,
            id=chatbot_pk,
            company=request.user.company,
        )

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
        if _has_active_sync_job(sync):
            return Response(
                _build_sync_status_response(sync),
                status=status.HTTP_202_ACCEPTED,
            )
        with transaction.atomic():
            job = SyncJob.objects.create(
                sync_type=SyncJob.JobType.JIRA,
                sync_id=sync.id,
                status=SyncStatusMixin.Status.QUEUED,
                status_message='Waiting to be processed.',
            )
            sync.sync_status = JiraSync.Status.QUEUED
            sync.sync_status_message = 'Sync job queued.'
            sync.current_job_id = str(job.id)
            sync.update_next_sync_at(reference_time=timezone.now(), assume_started=True)
            sync.save(
                update_fields=[
                    'sync_status',
                    'sync_status_message',
                    'current_job_id',
                    'next_sync_at',
                ]
            )
        return Response(
            _build_sync_status_response(sync),
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'])
    def status(self, request, chatbot_pk=None, pk=None):
        sync = self.get_object()
        return Response(
            _build_sync_status_response(sync),
            status=status.HTTP_200_OK,
        )

class ConfluenceSyncViewSet(viewsets.ModelViewSet):
    serializer_class = ConfluenceSyncSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]

    def _get_chatbot_pk(self):
        chatbot_id = self.kwargs.get('chatbot_pk')
        if not chatbot_id:
            raise PermissionDenied("Missing 'chatbot_id' in URL path.")
        try:
            return int(chatbot_id)
        except ValueError:
            raise ValidationError({'chatbot': ['A valid integer is required.']})

    def _validate_credential(self, credential):
        if credential and credential.company != self.request.user.company:
            raise NotFound("Credential not found.")

    def _validate_request_credential_id(self, data):
        credential_id = data.get('credential_id') or data.get('credential')
        if not credential_id:
            return
        try:
            credential_pk = int(credential_id)
        except (TypeError, ValueError):
            raise ValidationError({'credential_id': ['A valid integer is required.']})
        try:
            credential = Credential.objects.get(pk=credential_pk)
        except Credential.DoesNotExist:
            return
        self._validate_credential(credential)

    def get_queryset(self):
        chatbot_pk = self._get_chatbot_pk()
        return ConfluenceSync.objects.filter(chatBot__id=chatbot_pk, chatBot__company=self.request.user.company)

    def create(self, request, *args, **kwargs):
        chatbot_pk = self._get_chatbot_pk()
        chatBot = get_object_or_404(
            ChatBotInstance,
            id=chatbot_pk,
            company=request.user.company,
        )

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
        if _has_active_sync_job(sync):
            return Response(
                _build_sync_status_response(sync),
                status=status.HTTP_202_ACCEPTED,
            )
        with transaction.atomic():
            job = SyncJob.objects.create(
                sync_type=SyncJob.JobType.CONFLUENCE,
                sync_id=sync.id,
                status=SyncStatusMixin.Status.QUEUED,
                status_message='Waiting to be processed.',
            )
            sync.sync_status = ConfluenceSync.Status.QUEUED
            sync.sync_status_message = 'Sync job queued.'
            sync.current_job_id = str(job.id)
            sync.update_next_sync_at(reference_time=timezone.now(), assume_started=True)
            sync.save(
                update_fields=[
                    'sync_status',
                    'sync_status_message',
                    'current_job_id',
                    'next_sync_at',
                ]
            )
        return Response(
            _build_sync_status_response(sync),
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'])
    def status(self, request, chatbot_pk=None, pk=None):
        sync = self.get_object()
        return Response(
            _build_sync_status_response(sync),
            status=status.HTTP_200_OK,
        )

class ChatFeedbackViewSet(viewsets.ModelViewSet):
    serializer_class = ChatFeedbackSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]

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
            chat_bot_pk = int(chat_bot_id)
        except (TypeError, ValueError):
            raise ValidationError({'chatBot': ['A valid integer is required.']})

        try:
            return get_object_or_404(
                ChatBotInstance,
                pk=chat_bot_pk,
                company=self.request.user.company,
            )
        except Http404:
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
            raise NotFound('Chatbot not found.')
        feedback = serializer.save(chatBot=chatBot)
        upsert_feedback_document(feedback)

    def perform_update(self, serializer):
        feedback = serializer.instance
        if feedback.chatBot.company != self.request.user.company:
            raise NotFound('Chatbot not found.')

        updated = serializer.save()
        upsert_feedback_document(updated)

    def perform_destroy(self, instance):
        if instance.chatBot.company != self.request.user.company:
            raise NotFound('Chatbot not found.')

        delete_feedback_document(instance)
        super().perform_destroy(instance)

class GitCredentialViewSet(viewsets.ModelViewSet):
    serializer_class = GitCredentialSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]

    def get_queryset(self):
        return GitCredential.objects.filter(company=self.request.user.company)
    
    def perform_destroy(self, instance):
        if instance.company != self.request.user.company:
            raise PermissionDenied("You cannot delete git credentials for a different company")
        return super().perform_destroy(instance)
    
class GitRepoSyncViewSet(viewsets.ModelViewSet):
    serializer_class = GitRepoSyncSerializer
    permission_classes = [permissions.IsAuthenticated, IsCompanyAdminOrReadOnly]

    def _get_chatbot_pk(self):
        chatbot_id = self.kwargs.get('chatbot_pk')
        if not chatbot_id:
            raise PermissionDenied("Missing 'chatbot_id' in URL path.")
        try:
            return int(chatbot_id)
        except ValueError:
            raise ValidationError({'chatbot': ['A valid integer is required.']})

    def get_chatbot(self):
        chatbot_pk = self._get_chatbot_pk()
        return get_object_or_404(ChatBotInstance, id=chatbot_pk, company=self.request.user.company)

    def get_queryset(self):
        chatbot_pk = self._get_chatbot_pk()
        qs = GitRepoSync.objects.filter(chatBot__company=self.request.user.company)
        if chatbot_pk:
            qs = qs.filter(chatBot__id=chatbot_pk)
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

        if _has_active_sync_job(sync):
            return Response(
                _build_sync_status_response(sync),
                status=status.HTTP_202_ACCEPTED,
            )

        with transaction.atomic():
            job = SyncJob.objects.create(
                sync_type=SyncJob.JobType.GIT,
                sync_id=sync.id,
                status=SyncStatusMixin.Status.QUEUED,
                status_message='Waiting to be processed.',
            )
            sync.sync_status = GitRepoSync.Status.QUEUED
            sync.sync_status_message = 'Sync job queued.'
            sync.current_job_id = str(job.id)
            sync.update_next_sync_at(reference_time=timezone.now(), assume_started=True)
            sync.save(
                update_fields=[
                    'sync_status',
                    'sync_status_message',
                    'current_job_id',
                    'next_sync_at',
                ]
            )
        return Response(
            _build_sync_status_response(sync),
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=True, methods=['get'])
    def status(self, request, chatbot_pk=None, pk=None):
        sync = self.get_object()
        if sync.chatBot.company != request.user.company:
            raise PermissionDenied("You cannot view status for a repo outside your company")
        return Response(
            _build_sync_status_response(sync),
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
    chatbot = get_object_or_404(
        ChatBotInstance, id=chatbot_id, company=request.user.company
    )
    query = request.data.get("query")
    company_id = request.user.company_id
    try:
        top_k = int(request.data.get("top_k", DEFAULT_CHAT_TOP_K))
    except (TypeError, ValueError):
        raise ValidationError({"top_k": ["Must be an integer greater than or equal to 1."]})
    if top_k < 1:
        raise ValidationError({"top_k": ["Must be an integer greater than or equal to 1."]})
    if not query:
        return Response({"error": "Missing 'query' in request body"}, status=status.HTTP_400_BAD_REQUEST)

    try:
        results = search_documents(company_id, chatbot.id, query, top_k)
        return Response(results)
    except Exception as e:
        logger.error(f"Error querying documents: {e}")
        return Response({"error": "Failed to query documents"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

def _contains_enumeration_language(query: str) -> bool:
    """Return True when ``query`` asks for exhaustive listings."""

    lowered = query.lower()
    tokens = set(re.findall(r"\b\w+\b", lowered))
    if tokens & _ENUMERATION_TOKENS:
        return True

    return any(phrase in lowered for phrase in _ENUMERATION_PHRASES)


@api_view(['POST'])
def chat_with_bot(request, chatbot_id):
    """
    Chat endpoint using RAG.

    Example POST:
    {
        "query": "How do I deploy the app with Docker?",
        "top_k": 5
    }
    """
    chatbot = get_object_or_404(
        ChatBotInstance, id=chatbot_id, company=request.user.company
    )
    raw_query = request.data.get("query")
    company_id = request.user.company_id
    if not raw_query:
        return Response({"error": "Missing 'query' in request body"}, status=status.HTTP_400_BAD_REQUEST)

    query = str(raw_query).strip()

    if query.startswith('/feedback'):
        comment_payload = request.data.get('comment')
        comment_from_query = query[len('/feedback'):].strip()
        comment = (comment_payload or '').strip() or comment_from_query

        if not comment:
            raise ValidationError({'comment': ["Feedback comment cannot be empty."]})

        serializer = ChatFeedbackSerializer(data={'comment': comment})
        serializer.is_valid(raise_exception=True)
        feedback = serializer.save(chatBot=chatbot)
        upsert_feedback_document(feedback)

        return Response({'message': 'Thanks for your feedback!'}, status=status.HTTP_200_OK)

    top_k_value = request.data.get("top_k", DEFAULT_CHAT_TOP_K)
    try:
        top_k = int(top_k_value)
    except (TypeError, ValueError):
        raise ValidationError({"top_k": ["Must be an integer greater than or equal to 1."]})

    if top_k < 1:
        raise ValidationError({"top_k": ["Must be an integer greater than or equal to 1."]})

    top_k = min(top_k, MAX_CHAT_TOP_K)

    effective_top_k = top_k
    if _contains_enumeration_language(query):
        effective_top_k = max(effective_top_k, ENUMERATION_TOP_K)
        effective_top_k = min(effective_top_k, MAX_CHAT_TOP_K)

    history_data = request.data.get("history")
    validated_history = []
    if history_data is not None:
        if not isinstance(history_data, list):
            raise ValidationError({"history": ["Must be a list of prior turns."]})

        for index, turn in enumerate(history_data):
            if not isinstance(turn, dict):
                raise ValidationError(
                    {"history": [f"Turn {index + 1} must be an object with chatbot_id, user, and assistant fields."]}
                )

            turn_chatbot_id = turn.get("chatbot_id")
            if turn_chatbot_id != chatbot.id:
                raise ValidationError(
                    {
                        "history": [
                            f"Turn {index + 1} references chatbot {turn_chatbot_id}, which does not match chatbot {chatbot.id}."
                        ]
                    }
                )

            user_message = turn.get("user")
            assistant_message = turn.get("assistant")

            if not isinstance(user_message, str) or not user_message.strip():
                raise ValidationError(
                    {"history": [f"Turn {index + 1} must include a non-empty user message."]}
                )

            if assistant_message is not None and not isinstance(assistant_message, str):
                raise ValidationError(
                    {"history": [f"Turn {index + 1} assistant message must be a string if provided."]}
                )

            cleaned_turn = {
                "user": user_message.strip(),
                "assistant": (assistant_message or "").strip(),
            }
            validated_history.append(cleaned_turn)

    try:
        response = generate_answer(
            company_id,
            chatbot.id,
            query,
            top_k=effective_top_k,
            history=validated_history,
        )
        return Response(response)
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        return Response({"error": "Failed to generate answer"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)