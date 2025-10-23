import base64

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient
from unittest.mock import patch

from chat.encryption import fernet
from chat.models import Company, ChatBotInstance, Credential, GitCredential


User = get_user_model()


class IsCompanyAdminOrReadOnlyPermissionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.company = Company.objects.create(name="Acme Corp")
        self.upsert_patcher = patch('chat.views.upsert_feedback_document')
        self.mock_upsert = self.upsert_patcher.start()
        self.addCleanup(self.upsert_patcher.stop)

        self.viewer = User.objects.create_user(
            username="viewer", email="viewer@example.com", password="password123"
        )
        self.viewer.company = self.company
        self.viewer.role = User.Role.VIEWER
        self.viewer.is_staff = False
        self.viewer.save()

        self.company_admin = User.objects.create_user(
            username="company-admin", email="admin@example.com", password="password123"
        )
        self.company_admin.company = self.company
        self.company_admin.role = User.Role.ADMIN
        self.company_admin.is_staff = False
        self.company_admin.save()

        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Support Bot",
            description="Helps customers",
        )

        self.credential = Credential.objects.create(
            company=self.company,
            name="Primary Credential",
            email="service@example.com",
            _api_key=fernet.encrypt(b"initial-key").decode(),
        )

        self.git_credential = GitCredential.objects.create(
            company=self.company,
            name="Git Token",
            github_username="octocat",
            _token=fernet.encrypt(b"token").decode(),
        )

    def _post_as_unauthenticated(self, url, payload):
        client = APIClient()
        token = base64.b64encode(b'fake:fake').decode()
        client.credentials(HTTP_AUTHORIZATION=f'Basic {token}')
        return client.post(url, payload, format="json")

    def test_credential_writes_require_company_admin(self):
        url = "/api/credentials/"
        payload = {"name": "API", "email": "api@example.com", "api_key": "secret"}

        response = self._post_as_unauthenticated(url, payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.viewer)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.company_admin)
        response = self.client.post(
            url,
            {"name": "API", "email": "api-admin@example.com", "api_key": "secret"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_chatbot_writes_require_company_admin(self):
        url = "/api/chatBots/"
        payload = {"name": "Knowledge Bot", "description": "Answers questions"}

        response = self._post_as_unauthenticated(url, payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.viewer)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.company_admin)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_jira_sync_writes_require_company_admin(self):
        url = f"/api/chatBots/{self.chatbot.id}/jiraSyncs/"
        payload = {
            "board_url": "https://example.atlassian.net",
            "credential_id": self.credential.id,
            "sync_interval": "manual",
        }

        response = self._post_as_unauthenticated(url, payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.viewer)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.company_admin)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_confluence_sync_writes_require_company_admin(self):
        url = f"/api/chatBots/{self.chatbot.id}/confluenceSyncs/"
        payload = {
            "space_url": "https://example.atlassian.net/wiki",
            "credential_id": self.credential.id,
            "sync_interval": "manual",
        }

        response = self._post_as_unauthenticated(url, payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.viewer)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.company_admin)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_feedback_writes_require_company_admin(self):
        url = "/api/feedbacks/"
        payload = {"chatBot": self.chatbot.id, "comment": "Great answer"}

        response = self._post_as_unauthenticated(url, payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.viewer)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.company_admin)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_git_credential_writes_require_company_admin(self):
        url = "/api/gitCredentials/"
        payload = {
            "name": "Repo Access",
            "github_username": "builder",
            "token": "token-value",
        }

        response = self._post_as_unauthenticated(url, payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.viewer)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.company_admin)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_git_repo_sync_writes_require_company_admin(self):
        url = f"/api/chatBots/{self.chatbot.id}/gitRepoSyncs/"
        payload = {
            "repo_full_name": "octocat/hello-world",
            "branch": "main",
            "credential_id": self.git_credential.id,
            "sync_interval": "manual",
        }

        response = self._post_as_unauthenticated(url, payload)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

        self.client.force_authenticate(self.viewer)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.client.force_authenticate(self.company_admin)
        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
