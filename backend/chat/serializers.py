from rest_framework import serializers
from .models import Company, ChatBotInstance, JiraSync, ConfluenceSync, ChatFeedback, Credential, GitCredential, GitRepoSync, GitRepoFile
from django.contrib.auth import get_user_model
User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    can_manage_users = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'email',
            'company',
            'password',
            'role',
            'is_staff',
            'can_manage_users',
        ]
        extra_kwargs = {
            'password': {'write_only': True},
            'company': {'read_only': True},
            'role': {'required': False},
        }
        read_only_fields = ('company', 'is_staff', 'can_manage_users')

    def get_can_manage_users(self, obj):
        role = getattr(obj, 'role', None)
        is_staff = getattr(obj, 'is_staff', False)
        return bool(is_staff or role == User.Role.ADMIN)

    def create(self, validated_data):
        password = validated_data.pop('password')
        role = validated_data.pop('role', User.Role.ADMIN)
        user = User(**validated_data)
        user.role = role
        user.set_password(password)
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        request = self.context.get('request')
        actor = getattr(request, 'user', None) if request else None
        new_role = validated_data.pop('role', None)

        if new_role is not None:
            if not actor or not actor.is_authenticated:
                raise serializers.ValidationError({'role': 'Authentication required to modify roles.'})

            actor_role = getattr(actor, 'role', User.Role.ADMIN)

            if actor_role == User.Role.VIEWER and not actor.is_staff:
                raise serializers.ValidationError({'role': 'Viewers cannot modify roles.'})

            if instance == actor and new_role == User.Role.ADMIN:
                current_role = getattr(instance, 'role', User.Role.ADMIN)
                if not actor.is_staff and current_role != User.Role.ADMIN:
                    raise serializers.ValidationError({'role': 'You cannot promote yourself to admin.'})

            instance.role = new_role

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()
        return instance

class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Company
        fields = '__all__'

class CredentialSerializer(serializers.ModelSerializer):
    api_key = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = Credential
        fields = ['id', 'name', 'email', 'api_key', 'created_at']
        read_only_fields = ['created_at']

    def create(self, validated_data):
        raw_key = validated_data.pop('api_key')
        validated_data['company'] = self.context['request'].user.company

        cred = Credential(**validated_data)
        cred.api_key = raw_key
        cred.save()
        return cred

    def update(self, instance, validated_data):
        raw_key = validated_data.pop('api_key', None)
        if raw_key:
            instance.api_key = raw_key

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance

class ChatBotInstanceSerializer(serializers.ModelSerializer):
    class Meta:
        model = ChatBotInstance
        fields = '__all__'
        read_only_fields = ('company',)

class ChatFeedbackSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        comment = (attrs.get('comment') or '').strip()
        question = (attrs.get('question') or '').strip()
        answer = (attrs.get('answer') or '').strip()
        is_helpful = attrs.get('is_helpful', None)

        if comment:
            attrs['comment'] = comment

        if question:
            attrs['question'] = question

        if answer:
            attrs['answer'] = answer

        has_structured_feedback = bool(question and answer and is_helpful is not None)
        if not comment and not has_structured_feedback:
            raise serializers.ValidationError(
                'Provide a comment or complete the question, answer, and is_helpful fields.'
            )

        return super().validate(attrs)

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
    sync_interval = serializers.ChoiceField(choices=JiraSync.SYNC_INTERVAL_CHOICES, default='manual')

    class Meta:
        model = JiraSync
        fields = [
            'id',
            'board_url',
            'last_sync_time',
            'next_sync_at',
            'sync_status',
            'sync_status_message',
            'current_job_id',
            'credential',
            'credential_id',
            'sync_interval',
        ]
        read_only_fields = (
            'sync_status',
            'sync_status_message',
            'current_job_id',
            'last_sync_time',
            'next_sync_at',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            self.fields['credential_id'].queryset = Credential.objects.filter(
                company=request.user.company
            )

class ConfluenceSyncSerializer(serializers.ModelSerializer):
    credential = CredentialSummarySerializer(read_only=True)
    credential_id = serializers.PrimaryKeyRelatedField(
        queryset=Credential.objects.all(),
        write_only=True,
        source='credential',
    )
    sync_interval = serializers.ChoiceField(choices=ConfluenceSync.SYNC_INTERVAL_CHOICES, default='manual')

    class Meta:
        model = ConfluenceSync
        fields = [
            'id',
            'space_url',
            'last_sync_time',
            'next_sync_at',
            'sync_status',
            'sync_status_message',
            'current_job_id',
            'credential',
            'credential_id',
            'sync_interval',
        ]
        read_only_fields = (
            'sync_status',
            'sync_status_message',
            'current_job_id',
            'last_sync_time',
            'next_sync_at',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            self.fields['credential_id'].queryset = Credential.objects.filter(
                company=request.user.company
            )

class GitCredentialSerializer(serializers.ModelSerializer):
    token = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = GitCredential
        fields = ['id', 'name', 'github_username', 'token', 'created_at']
        read_only_fields = ['created_at']

    def create(self, validated_data):
        raw_token = validated_data.pop('token')
        validated_data['company'] = self.context['request'].user.company

        git_cred = GitCredential(**validated_data)
        git_cred.token = raw_token 
        git_cred.save()
        return git_cred

    def update(self, instance, validated_data):
        raw_token = validated_data.pop('token', None)
        if raw_token:
            instance.token = raw_token

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return instance
    
class GitCredentialSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = GitCredential
        fields = ['id', 'name', 'github_username']

class GitRepoSyncSerializer(serializers.ModelSerializer):
    credential = GitCredentialSummarySerializer(read_only=True)
    credential_id = serializers.PrimaryKeyRelatedField(
        queryset=GitCredential.objects.all(),
        write_only=True,
        source='credential',
    )
    sync_interval = serializers.ChoiceField(
        choices=GitRepoSync.SYNC_INTERVAL_CHOICES,
        default='manual'
    )

    class Meta:
        model = GitRepoSync
        fields = [
            'id',
            'repo_full_name',
            'branch',
            'last_sync_time',
            'next_sync_at',
            'sync_status',
            'sync_status_message',
            'current_job_id',
            'sync_interval',
            'credential',
            'credential_id',
        ]
        read_only_fields = (
            'sync_status',
            'sync_status_message',
            'current_job_id',
            'last_sync_time',
            'next_sync_at',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        req = self.context.get('request')
        if req and req.user.is_authenticated:
            self.fields['credential_id'].queryset = GitCredential.objects.filter(
                company=req.user.company
            )

class GitRepoFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = GitRepoFile
        fields = ['id', 'path', 'sha', 'size', 'url', 'content', 'last_updated']
