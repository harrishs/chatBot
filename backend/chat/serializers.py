from rest_framework import serializers
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'

class ChatBotInstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatBotInstance
        fields = '__all__'
        read_only_fields = ('company',)

class JiraSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = JiraSync
        fields = '__all__'
        read_only_fields = ('chatBot',)

class ConfluenceSyncSerializer(serializers.ModelSerializer):
    class Meta:
        model = ConfluenceSync
        fields = '__all__'
        read_only_fields = ('chatBot',)

class ChatFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatFeedback
        fields = '__all__'
        read_only_fields = ('chatBot',)
