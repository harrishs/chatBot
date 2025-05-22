from django.shortcuts import render
from rest_framework import viewsets, permissions
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback, Credential
from .serializers import CompanySerializer, ChatBotInstanceSerializer, JiraSyncSerializer, ConfluenceSyncSerializer, ChatFeedbackSerializer, UserSerializer, CredentialSerializer
from django.contrib.auth import get_user_model

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
        return JiraSync.objects.filter(chatBot__company=self.request.user.company)
    
    def perform_create(self, serializer):
        chatBot = serializer.validated_data['chatBot']
        if chatBot.company != self.request.user.company:
            raise PermissionError("You cannot create a sync for a chatbot outside your company")
        serializer.save()

class ConfluenceSyncViewSet(viewsets.ModelViewSet):
    serializer_class = ConfluenceSyncSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ConfluenceSync.objects.filter(chatBot__company=self.request.user.company)
    
    def perform_create(self, serializer):
        chatBot = serializer.validated_data['chatBot']
        if chatBot.company != self.request.user.company:
            raise PermissionError("You cannot create a sync for a chatbot outside your company")
        serializer.save()

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
