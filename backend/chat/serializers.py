from rest_framework import serializers
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback
from django.contrib.auth import get_user_model
User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'company', 'password']
        extra_kwargs = {
            'password': {'write_only': True},
            'company': {'read_only': True},
        }

    def create(self, validated_data):
        password = validated_data.pop('password')
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user

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
