import os

import django
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("ENCRYPTION_KEY", "wvRwBW8Y7-P2eFoRhqNRdbi8ZjsIvkTCmFll1xQ3hl8=")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DJANGO_SECRET_KEY", "unit-test-secret")

django.setup()

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
        mock_choice = SimpleNamespace(
            message=SimpleNamespace(content="final answer referencing [jira:PROJ-1]")
        )
        mock_response = SimpleNamespace(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_response

        documents = [
            {
                "source": "jira",
                "source_id": "PROJ-1",
                "source_display": "PROJ-1",
                "source_url": "https://example.atlassian.net/browse/PROJ-1",
                "content": "Issue title\nA concise update about the fix.",
                "metadata": {
                    "title": "Issue title",
                    "chunk_text": "Issue title\nA concise update about the fix.",
                    "chunk_index": 0,
                    "chunk_count": 1,
                    "source_url": "https://example.atlassian.net/browse/PROJ-1",
                },
                "similarity": 0.91,
            }
        ]

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ) as mock_search_documents, patch(
            "chat.utils.rag.rerank_documents", return_value=documents
        ) as mock_rerank_documents:
            result = rag.generate_answer(company_id=1, chatbot_id=2, query="question")

        self.assertEqual(result["answer"], "final answer referencing [jira:PROJ-1]")
        self.assertEqual(len(result["sources"]), 1)
        metadata_entry = result["sources"][0]
        self.assertEqual(metadata_entry["source"], "jira")
        self.assertEqual(metadata_entry["source_id"], "PROJ-1")
        self.assertEqual(metadata_entry["source_display"], "PROJ-1")
        self.assertEqual(metadata_entry["source_url"], "https://example.atlassian.net/browse/PROJ-1")
        self.assertEqual(metadata_entry["similarity"], 0.91)
        self.assertEqual(metadata_entry["title"], "Issue title")
        self.assertEqual(metadata_entry["summary"], "Issue title A concise update about the fix.")
        self.assertEqual(metadata_entry["excerpt"], "Issue title\nA concise update about the fix.")
        self.assertEqual(metadata_entry["snippet"], "Issue title\nA concise update about the fix.")
        self.assertEqual(metadata_entry["keywords"], "issue, title, concise, update, fix.")
        self.assertEqual(metadata_entry["chunk_index"], 0)
        self.assertEqual(metadata_entry["chunk_count"], 1)
        mock_client.chat.completions.create.assert_called_once()
        mock_search_documents.assert_called_once_with(1, 2, "question", 5)
        mock_rerank_documents.assert_called_once_with("question", documents)

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(item["content"] for item in messages if item["role"] == "user")
        self.assertIn("Title: Issue title", user_content)
        self.assertIn("Snippet:\nIssue title\nA concise update about the fix.", user_content)

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
        ), patch("chat.utils.rag.rerank_documents", return_value=[]):
            with self.assertRaises(RuntimeError):
                rag.generate_answer(company_id=1, chatbot_id=2, query="question")

    @override_settings(OPENAI_API_KEY="test-key")
    def test_generate_answer_sanitizes_code_and_ensures_citations(self):
        mock_client = Mock()
        mock_choice = SimpleNamespace(
            message=SimpleNamespace(
                content="Here is what you asked:\n```python\nprint('secret')\n```"
            )
        )
        mock_response = SimpleNamespace(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_response

        documents = [
            {
                "source": "github",
                "source_id": "app/main.py",
                "source_display": "app/main.py",
                "content": "main.py\nImplements the entry point.",
                "metadata": {
                    "title": "main.py",
                    "path": "app/main.py",
                    "chunk_text": "def run():\n    print('hello world')",
                    "chunk_index": 0,
                    "chunk_count": 1,
                },
                "similarity": 0.77,
            }
        ]

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ), patch("chat.utils.rag.rerank_documents", return_value=documents):
            result = rag.generate_answer(company_id=1, chatbot_id=2, query="Show me the code")

        self.assertNotIn("```", result["answer"])
        self.assertIn("Sources: [github:app/main.py]", result["answer"])
        self.assertIn("[omitted code block]", result["answer"])
        self.assertEqual(
            result["sources"],
            [
                {
                    "source": "github",
                    "source_id": "app/main.py",
                    "source_display": "app/main.py",
                    "similarity": 0.77,
                    "title": "main.py",
                    "summary": "def run(): print('hello world')",
                    "excerpt": "def run():\nprint('hello world')",
                    "snippet": "def run():\n    print('hello world')",
                    "keywords": "def, run, print, hello, world",
                    "path": "app/main.py",
                    "chunk_index": 0,
                    "chunk_count": 1,
                }
            ],
        )

    @override_settings(OPENAI_API_KEY="test-key")
    def test_generate_answer_prompt_includes_git_snippet_and_path(self):
        mock_client = Mock()
        mock_choice = SimpleNamespace(message=SimpleNamespace(content="Acknowledged [github:app/main.py]"))
        mock_response = SimpleNamespace(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_response

        documents = [
            {
                "source": "github",
                "source_id": "app/main.py",
                "source_display": "app/main.py",
                "content": "main.py",
                "metadata": {
                    "title": "main.py",
                    "path": "app/main.py",
                    "chunk_text": "print('ready')",
                    "chunk_index": 0,
                    "chunk_count": 1,
                },
                "similarity": 0.52,
            }
        ]

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ), patch("chat.utils.rag.rerank_documents", return_value=documents):
            rag.generate_answer(company_id=1, chatbot_id=2, query="status?")

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(item["content"] for item in messages if item["role"] == "user")
        self.assertIn("Path: app/main.py", user_content)
        self.assertIn("Snippet:\nprint('ready')", user_content)

    @override_settings(OPENAI_API_KEY="test-key")
    def test_generate_answer_prompt_includes_confluence_title_and_snippet(self):
        mock_client = Mock()
        mock_choice = SimpleNamespace(message=SimpleNamespace(content="See [confluence:Release Doc]"))
        mock_response = SimpleNamespace(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_response

        documents = [
            {
                "source": "confluence",
                "source_id": "page-1",
                "source_display": "Release Doc",
                "content": "Release Notes",
                "metadata": {
                    "title": "Release Notes",
                    "section_heading": "Overview",
                    "chunk_text": "The release introduces key capabilities.",
                    "chunk_index": 1,
                    "chunk_count": 3,
                },
                "similarity": 0.63,
            }
        ]

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ), patch("chat.utils.rag.rerank_documents", return_value=documents):
            rag.generate_answer(company_id=1, chatbot_id=2, query="What's new?")

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(item["content"] for item in messages if item["role"] == "user")
        self.assertIn("Title: Release Notes", user_content)
        self.assertIn("Section: Overview", user_content)
        self.assertIn("Snippet:\nThe release introduces key capabilities.", user_content)

    @override_settings(OPENAI_API_KEY="test-key")
    def test_generate_answer_redacts_sensitive_values_without_losing_context(self):
        mock_client = Mock()
        mock_choice = SimpleNamespace(
            message=SimpleNamespace(
                content="Use token=abc12345 when syncing configs [github:app/config.yaml]"
            )
        )
        mock_response = SimpleNamespace(choices=[mock_choice])
        mock_client.chat.completions.create.return_value = mock_response

        documents = [
            {
                "source": "github",
                "source_id": "app/config.yaml",
                "source_display": "app/config.yaml",
                "content": "config.yaml\nContains environment defaults.",
                "metadata": {
                    "title": "config.yaml",
                    "path": "app/config.yaml",
                    "chunk_text": "token=abc12345\nmode=sync",
                    "chunk_index": 0,
                    "chunk_count": 1,
                },
                "similarity": 0.68,
            }
        ]

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ), patch("chat.utils.rag.rerank_documents", return_value=documents):
            result = rag.generate_answer(
                company_id=1, chatbot_id=2, query="How do I sync configs?"
            )

        self.assertIn("token= [redacted sensitive data]", result["answer"])
        self.assertIn("[github:app/config.yaml]", result["answer"])
        self.assertNotIn("abc12345", result["answer"])

    @override_settings(OPENAI_API_KEY="test-key")
    def test_generate_answer_network_error(self):
        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = APITimeoutError(
            httpx.Request("POST", "https://api.openai.com")
        )

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=[]
        ), patch("chat.utils.rag.rerank_documents", return_value=[]):
            with self.assertRaises(RuntimeError):
                rag.generate_answer(company_id=1, chatbot_id=2, query="question")
