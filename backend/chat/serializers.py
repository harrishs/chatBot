from rest_framework import serializers
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback, Credential
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

class CredentialSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True)
    decrypted_key = serializers.CharField(read_only=True)

    class Meta:
        model = Credential
        fields = ['id', 'name', 'email', 'api_key', 'decrypted_key', 'created_at']
        read_only_fields = ['created_at']

    def create(self, validated_data):
        request = self.context['request']
        company = request.user.company
        validated_data.pop('company', None)  # Ensure company is not in validated_data
        api_key = validated_data.pop('api_key')

        cred = Credential(**validated_data, company=company)
        cred.api_key = api_key
        cred.save()
        return cred

    def update(self, instance, validated_data):
        api_key = validated_data.pop('api_key', None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if api_key:
            instance.api_key = api_key
        instance.save()
        return instance
    
    def get_decrypted_key(self, obj):
        return obj.api_key

class ChatBotInstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatBotInstance
        fields = '__all__'
        read_only_fields = ('company',)

class ChatFeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatFeedback
        fields = '__all__'
        read_only_fields = ('chatBot',)

class CredentialSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Credential
        fields = ['id', 'name', 'email']

class JiraSyncSerializer(serializers.ModelSerializer):
    credential = CredentialSummarySerializer(read_only=True)
    credential_id = serializers.PrimaryKeyRelatedField(
        queryset=Credential.objects.all(),
        write_only=True,
        source='credential',
    )

    class Meta:
        model = JiraSync
        fields = ['id', 'board_url', 'last_sync_time', 'credential', 'credential_id']

class ConfluenceSyncSerializer(serializers.ModelSerializer):
    credential = CredentialSummarySerializer(read_only=True)
    credential_id = serializers.PrimaryKeyRelatedField(
        queryset=Credential.objects.all(),
        write_only=True,
        source='credential',
    )

    class Meta:
        model = ConfluenceSync
        fields = ['id', 'space_url', 'last_sync_time', 'credential', 'credential_id']