from django.shortcuts import render
from rest_framework import viewsets
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback
from .serializers import CompanySerializer, ChatBotInstanceSerializer, JiraSyncSerializer, ConfluenceSyncSerializer, ChatFeedbackSerializer

class CompanyViewSet(viewsets.ModelViewSet):
    queryset = Company.objects.all()
    serializer_class = CompanySerializer

class ChatBotInstanceViewSet(viewsets.ModelViewSet):
    queryset = ChatBotInstance.objects.all()
    serializer_class = ChatBotInstanceSerializer

class JiraSyncViewSet(viewsets.ModelViewSet):
    queryset = JiraSync.objects.all()
    serializer_class = JiraSyncSerializer

class ConfluenceSyncViewSet(viewsets.ModelViewSet):
    queryset = ConfluenceSync.objects.all()
    serializer_class = ConfluenceSyncSerializer

class ChatFeedbackViewSet(viewsets.ModelViewSet):
    queryset = ChatFeedback.objects.all()
    serializer_class = ChatFeedbackSerializer
