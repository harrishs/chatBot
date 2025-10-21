from django.contrib.auth import get_user_model
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from chat.models import ChatBotInstance, ChatFeedback, Company, Document


User = get_user_model()


class ChatFeedbackAPITests(APITestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Feedback Co")
        self.other_company = Company.objects.create(name="Other Co")

        self.chatbot = ChatBotInstance.objects.create(
            company=self.company,
            name="Feedback Bot",
        )
        self.other_chatbot = ChatBotInstance.objects.create(
            company=self.other_company,
            name="Other Bot",
        )

        self.user = User.objects.create_user(
            username="feedback-user",
            email="feedback@example.com",
            password="feedbackpass123",
            company=self.company,
        )

        self.client.force_authenticate(self.user)
        self.url = reverse('feedback-list')

    @patch("chat.utils.embeddings.embed_text", return_value=[0.05] * 1536)
    def test_create_feedback_for_own_chatbot(self, mock_embed_text):
        payload = {
            'question': 'How do I reset my password?',
            'answer': 'Follow the reset link.',
            'is_helpful': True,
            'chatBot': self.chatbot.id,
        }

        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ChatFeedback.objects.count(), 1)
        mock_embed_text.assert_called_once()
        feedback = ChatFeedback.objects.get()
        self.assertEqual(feedback.chatBot, self.chatbot)
        self.assertEqual(feedback.question, payload['question'])
        self.assertEqual(feedback.answer, payload['answer'])
        self.assertTrue(feedback.is_helpful)

        document = Document.objects.get(source="feedback")
        self.assertEqual(document.source_id, f"feedback-{feedback.id}")
        self.assertEqual(document.metadata.get("question"), payload['question'])
        self.assertEqual(document.metadata.get("answer"), payload['answer'])

    def test_cannot_create_feedback_for_other_company_chatbot(self):
        payload = {
            'question': 'Can I access another tenant bot?',
            'answer': 'No access.',
            'is_helpful': False,
            'chatBot': self.other_chatbot.id,
        }

        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(ChatFeedback.objects.count(), 0)

    def test_cannot_create_feedback_with_other_company_chatbot_alias(self):
        payload = {
            'question': 'Alias access check?',
            'answer': 'Still no.',
            'is_helpful': False,
            'chatbot': self.other_chatbot.id,
        }

        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(ChatFeedback.objects.count(), 0)

    def test_create_feedback_rejects_non_integer_chatbot_value(self):
        payload = {
            'question': 'What is the support email?',
            'answer': 'support@example.com',
            'is_helpful': True,
            'chatBot': 'not-a-number',
        }

        response = self.client.post(self.url, payload, format='json')

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {'chatBot': ['A valid integer is required.']})
        self.assertEqual(ChatFeedback.objects.count(), 0)

    def test_create_feedback_rejects_non_integer_chatbot_query_param(self):
        payload = {
            'question': 'How do I change my plan?',
            'answer': 'Visit billing settings.',
            'is_helpful': False,
        }

        response = self.client.post(
            f"{self.url}?chatBot=invalid",
            payload,
            format='json',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.data, {'chatBot': ['A valid integer is required.']})
        self.assertEqual(ChatFeedback.objects.count(), 0)
