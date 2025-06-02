from django.shortcuts import render
from rest_framework import viewsets, permissions
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback, Credential
from .serializers import CompanySerializer, ChatBotInstanceSerializer, JiraSyncSerializer, ConfluenceSyncSerializer, ChatFeedbackSerializer, UserSerializer, CredentialSerializer
from django.contrib.auth import get_user_model
import logging
from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied

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

    def get_queryset(self):
        chatbot_id = self.kwargs['chatbot_id']
        return JiraSync.objects.filter(chatBot__id=chatbot_id, chatBot__company=self.request.user.company)
    
    def create(self, request, *args, **kwargs):
        # Attach the chatbot manually since it's passed through the URL
        chatbot_id = self.kwargs['chatbot_id']

        try:
            chatBot = ChatBotInstance.objects.get(id=chatbot_id, company=request.user.company)
        except ChatBotInstance.DoesNotExist:
            raise PermissionDenied("❌ Invalid chatbot or not in your company")

        # Include the chatbot in the validated data
        mutable_data = request.data.copy()
        mutable_data['chatBot'] = chatBot.id

        serializer = self.get_serializer(data=mutable_data)

        if not serializer.is_valid():
            logger.error("❌ Validation error: %s", serializer.errors)
            return Response(serializer.errors, status=400)

        serializer.save(chatBot=chatBot)
        return Response(serializer.data, status=201)

class ConfluenceSyncViewSet(viewsets.ModelViewSet):
    serializer_class = ConfluenceSyncSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        chatbot_id = self.kwargs['chatbot_id']
        return ConfluenceSync.objects.filter(chatBot__id=chatbot_id, chatBot__company=self.request.user.company)
    
    def create(self, request, *args, **kwargs):
        chatbot_id = self.kwargs['chatbot_id']

        try:
            chatBot = ChatBotInstance.objects.get(
                id=chatbot_id,
                company=request.user.company
            )
        except ChatBotInstance.DoesNotExist:
            raise PermissionDenied("❌ Invalid chatbot or not in your company")

        # Inject chatBot into the data explicitly
        mutable_data = request.data.copy()
        mutable_data['chatBot'] = chatBot.id

        serializer = self.get_serializer(data=mutable_data)

        if not serializer.is_valid():
            logger.error("❌ ConfluenceSync Validation Error: %s", serializer.errors)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        serializer.save(chatBot=chatBot)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

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
