from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase, override_settings
from openai import APIConnectionError, APITimeoutError, RateLimitError

from chat.utils.embeddings import embed_text
from chat.utils import rag


class EmbedTextTests(SimpleTestCase):
    @override_settings(OPENAI_API_KEY="test-key")
    def test_embed_text_success(self):
        mock_client = Mock()
        mock_response = Mock()
        mock_response.data = [SimpleNamespace(embedding=[0.1, 0.2])]
        mock_client.embeddings.create.return_value = mock_response

        with patch("chat.utils.embeddings.get_openai_client", return_value=mock_client):
            result = embed_text("hello world")

        self.assertEqual(result, [0.1, 0.2])
        mock_client.embeddings.create.assert_called_once_with(
            model="text-embedding-3-small",
            input="hello world",
        )

    @override_settings(OPENAI_API_KEY="test-key")
    def test_embed_text_rate_limit_error(self):
        mock_client = Mock()
        request = httpx.Request("POST", "https://api.openai.com/v1/embeddings")
        response = httpx.Response(status_code=429, request=request)
        mock_client.embeddings.create.side_effect = RateLimitError(
            "rate limit", response=response, body=None
        )

        with patch("chat.utils.embeddings.get_openai_client", return_value=mock_client):
            with self.assertRaises(RuntimeError):
                embed_text("hello world")

    @override_settings(OPENAI_API_KEY="test-key")
    def test_embed_text_network_error(self):
        mock_client = Mock()
        mock_client.embeddings.create.side_effect = APIConnectionError(
            message="connection", request=httpx.Request("POST", "https://api.openai.com")
        )

        with patch("chat.utils.embeddings.get_openai_client", return_value=mock_client):
            with self.assertRaises(RuntimeError):
                embed_text("hello world")


class GenerateAnswerTests(SimpleTestCase):
    @override_settings(OPENAI_API_KEY="test-key")
    def test_generate_answer_success(self):
        mock_client = Mock()
        mock_choice = SimpleNamespace(message=SimpleNamespace(content="final answer"))
        mock_response = SimpleNamespace(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_response

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=[{"source": "jira", "source_id": "1", "content": "data"}]
        ) as mock_search_documents:
            result = rag.generate_answer(company_id=1, chatbot_id=2, query="question")

        self.assertEqual(
            result,
            {
                "answer": "final answer",
                "sources": [{"source": "jira", "source_id": "1", "content": "data"}],
            },
        )
        mock_client.chat.completions.create.assert_called_once()
        mock_search_documents.assert_called_once_with(1, 2, "question", 5)

    @override_settings(OPENAI_API_KEY="test-key")
    def test_generate_answer_rate_limit_error(self):
        mock_client = Mock()
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(status_code=429, request=request)
        mock_client.chat.completions.create.side_effect = RateLimitError(
            "rate limit", response=response, body=None
        )

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=[]
        ):
            with self.assertRaises(RuntimeError):
                rag.generate_answer(company_id=1, chatbot_id=2, query="question")

    @override_settings(OPENAI_API_KEY="test-key")
    def test_generate_answer_network_error(self):
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = APITimeoutError(
            httpx.Request("POST", "https://api.openai.com")
        )

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=[]
        ):
            with self.assertRaises(RuntimeError):
                rag.generate_answer(company_id=1, chatbot_id=2, query="question")
