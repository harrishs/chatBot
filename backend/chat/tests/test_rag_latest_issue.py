from datetime import timedelta

from django.test import TestCase, override_settings
from django.utils import timezone
from unittest.mock import patch

from chat.models import ChatBotInstance, Company, JiraIssue, JiraSync
from chat.utils import rag


class LatestResolvedIssueTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Acme")
        self.chatbot = ChatBotInstance.objects.create(company=self.company, name="Helper")
        self.sync = JiraSync.objects.create(chatBot=self.chatbot, board_url="https://jira.example.com")

    @override_settings(OPENAI_API_KEY="")
    def test_generate_answer_returns_latest_resolved_issue(self):
        now = timezone.now()
        JiraIssue.objects.create(
            sync=self.sync,
            issue_key="ACME-101",
            summary="Fix login bug",
            description="",
            status="Done",
            status_category="done",
            assignee="Jane",
            resolution="Fixed",
            resolution_date=now - timedelta(days=2),
            created_at=now - timedelta(days=10),
            updated_at=now - timedelta(days=2),
        )
        latest_issue = JiraIssue.objects.create(
            sync=self.sync,
            issue_key="ACME-202",
            summary="Improve onboarding flow",
            description="",
            status="Released",
            status_category="done",
            assignee="John",
            resolution="Completed",
            resolution_date=now - timedelta(hours=6),
            created_at=now - timedelta(days=5),
            updated_at=now - timedelta(hours=1),
        )

        with patch("chat.utils.rag.get_openai_client") as mock_client, patch(
            "chat.utils.rag.search_documents"
        ) as mock_search, patch("chat.utils.rag.rerank_documents") as mock_rerank:
            result = rag.generate_answer(
                company_id=self.company.id,
                chatbot_id=self.chatbot.id,
                query="What is the latest resolved Jira ticket?",
            )

        mock_client.assert_not_called()
        mock_search.assert_not_called()
        mock_rerank.assert_not_called()

        self.assertIn(latest_issue.issue_key, result["answer"])
        self.assertIn(latest_issue.status, result["answer"])
        self.assertIn(latest_issue.resolution, result["answer"])
        self.assertIn("[jira:ACME-202]", result["answer"])

        self.assertEqual(len(result["sources"]), 1)
        metadata = result["sources"][0]
        self.assertEqual(metadata["source"], "jira")
        self.assertEqual(metadata["source_id"], latest_issue.issue_key)
        self.assertEqual(metadata["status"], latest_issue.status)
        self.assertEqual(metadata["resolution"], latest_issue.resolution)
        self.assertEqual(metadata["resolution_date"], latest_issue.resolution_date.isoformat())

    def test_generate_answer_handles_no_resolved_issues(self):
        JiraIssue.objects.create(
            sync=self.sync,
            issue_key="ACME-303",
            summary="Investigate outage",
            description="",
            status="In Progress",
            status_category="in-progress",
            assignee="Chris",
            resolution=None,
            resolution_date=None,
            created_at=timezone.now() - timedelta(days=1),
            updated_at=timezone.now() - timedelta(hours=1),
        )

        result = rag.answer_latest_resolved_issue(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
        )

        self.assertEqual(result["sources"], [])
        self.assertIn("could not find any resolved jira issues", result["answer"].lower())
