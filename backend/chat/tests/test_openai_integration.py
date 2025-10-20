import os

import django
from typing import List
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
    def setUp(self):
        super().setUp()
        self._embed_patch = patch("chat.utils.rag.embed_text", return_value=[0.1, 0.2, 0.3])
        self.mock_embed = self._embed_patch.start()

    def tearDown(self):
        self._embed_patch.stop()
        super().tearDown()

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
                "combined_score": 0.91,
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
        self.assertGreaterEqual(result["confidence"], 0.9)
        self.assertAlmostEqual(result["retrieval_confidence"], 0.91)
        self.assertIn("drafts", result)
        self.assertGreaterEqual(len(result["drafts"]), 1)
        self.assertEqual(result["drafts"][0]["answer"], result["answer"])
        self.assertEqual(result["drafts"][0]["raw_answer"], "final answer referencing [jira:PROJ-1]")
        self.assertIn("[jira:PROJ-1]", result["drafts"][0]["citations"])
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
        mock_search_documents.assert_called_once_with(
            1, 2, "question", 5, query_embedding=[0.1, 0.2, 0.3]
        )
        mock_rerank_documents.assert_called_once()
        rerank_call = mock_rerank_documents.call_args
        self.assertEqual(rerank_call.args[0], "question")
        self.assertEqual(len(rerank_call.args[1]), len(documents))

        messages = mock_client.chat.completions.create.call_args.kwargs["messages"]
        user_content = next(item["content"] for item in messages if item["role"] == "user")
        self.assertIn("[jira:PROJ-1]", user_content)
        self.assertIn("Issue title A concise update about the fix.", user_content)
        self.assertNotIn("n", mock_client.chat.completions.create.call_args.kwargs)

    @override_settings(
        OPENAI_API_KEY="test-key",
        RAG_QUERY_REWRITE_MODEL="gpt-4o-mini",
        RAG_QUERY_REWRITE_THRESHOLD=0.6,
        RAG_LOW_CONFIDENCE_THRESHOLD=0.8,
    )
    def test_generate_answer_rewrites_query_when_low_confidence(self):
        rewrite_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='["better keywords"]')
                )
            ]
        )
        final_response = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content="final answer referencing [confluence:CONF-2]"
                    )
                )
            ]
        )

        mock_client = Mock()
        mock_client.chat.completions.create.side_effect = [rewrite_response, final_response]

        initial_documents = [
            {
                "id": 11,
                "source": "jira",
                "source_id": "LOW-1",
                "source_display": "LOW-1",
                "content": "Unrelated status",
                "metadata": {"title": "Unhelpful", "chunk_text": "Unrelated status"},
                "combined_score": 0.05,
                "similarity": 0.05,
                "normalized_score": 1.0,
            }
        ]

        rewrite_documents = [
            {
                "id": 22,
                "source": "confluence",
                "source_id": "CONF-2",
                "source_display": "CONF-2",
                "content": "Detailed launch checklist",
                "metadata": {
                    "title": "Launch Checklist",
                    "chunk_text": "Detailed launch checklist",
                },
                "combined_score": 0.85,
                "similarity": 0.5,
                "normalized_score": 1.0,
            }
        ]

        search_queries: List[str] = []

        def _search_side_effect(
            company_id,
            chatbot_id,
            query,
            top_k,
            sources=None,
            query_embedding=None,
        ):
            search_queries.append(query)
            if query == "question":
                return initial_documents
            if query == "better keywords":
                return rewrite_documents
            return []

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents",
            side_effect=_search_side_effect,
        ) as mock_search_documents, patch(
            "chat.utils.rag.rerank_documents",
            side_effect=lambda q, docs: list(docs),
        ), patch(
            "chat.utils.rag.record_retrieval_fallback_event"
        ) as mock_record_event:
            result = rag.generate_answer(company_id=1, chatbot_id=2, query="question")

        self.assertEqual(mock_client.chat.completions.create.call_count, 2)
        self.assertGreaterEqual(search_queries.count("question"), 1)
        self.assertIn("better keywords", search_queries)
        self.assertEqual(result["answer"], "final answer referencing [confluence:CONF-2]")
        self.assertEqual(result["sources"][0]["source_id"], "CONF-2")
        reasoning = result["reasoning_trace"].get("query_rewrite")
        self.assertIsNotNone(reasoning)
        self.assertIn("better keywords", reasoning.get("rewrites", []))
        first_call = mock_search_documents.call_args_list[0]
        self.assertEqual(first_call.args[:4], (1, 2, "question", 5))
        self.assertEqual(first_call.kwargs.get("query_embedding"), [0.1, 0.2, 0.3])
        self.assertTrue(
            any(
                (len(call.args) > 2 and call.args[2] == "better keywords")
                or call.kwargs.get("query") == "better keywords"
                for call in mock_search_documents.call_args_list
            )
        )
        mock_record_event.assert_called()

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
                content=(
                    "Here is what you asked:\n"
                    "```bash\n"
                    "echo 'ready'\n"
                    "api_key=super-secret\n"
                    "```\n"
                    "Remember to run `npm install`.\n"
                    "Do not expose sk-1234567890abcdefghijkl."
                )
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

        self.assertIn("```bash", result["answer"])
        self.assertIn("echo 'ready'", result["answer"])
        self.assertIn("api_key= [redacted sensitive data]", result["answer"])
        self.assertNotIn("super-secret", result["answer"])
        self.assertIn("Remember to run `npm install`.", result["answer"])
        self.assertIn("[redacted sensitive data]", result["answer"])
        self.assertNotIn("sk-1234567890abcdefghijkl", result["answer"])
        self.assertIn("Sources: [github:app/main.py]", result["answer"])
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
                    "chunk_text": "def run():\n    print('hello world')",
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
        self.assertIn("[github:app/main.py]", user_content)
        self.assertIn("main.py", user_content)
        self.assertIn("print('ready')", user_content)

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
        self.assertIn("[confluence:Release Doc]", user_content)
        self.assertIn("Release Notes", user_content)
        self.assertIn("The release introduces key capabilities.", user_content)

    @override_settings(OPENAI_API_KEY="test-key", RAG_MIN_DRAFT_COUNT=3)
    def test_generate_answer_consensus_prefers_shared_citations(self):
        mock_client = Mock()
        consensus_choice = SimpleNamespace(
            message=SimpleNamespace(
                content="Answer referencing [jira:PROJ-1] with details"
            )
        )
        second_consensus_choice = SimpleNamespace(
            message=SimpleNamespace(
                content="Follow-up also citing [jira:PROJ-1] for clarity"
            )
        )
        outlier_choice = SimpleNamespace(
            message=SimpleNamespace(
                content="Conflicting summary with [jira:PROJ-2] and [confluence:CONF-1]"
            )
        )
        mock_response = SimpleNamespace(
            choices=[outlier_choice, consensus_choice, second_consensus_choice]
        )
        mock_client.chat.completions.create.return_value = mock_response

        documents = [
            {
                "source": "jira",
                "source_id": "PROJ-1",
                "source_display": "PROJ-1",
                "content": "Primary fix details",
                "metadata": {
                    "title": "Primary Fix",
                    "chunk_text": "Primary fix details",
                },
                "combined_score": 0.92,
                "similarity": 0.92,
            },
            {
                "source": "jira",
                "source_id": "PROJ-2",
                "source_display": "PROJ-2",
                "content": "Secondary update",
                "metadata": {
                    "title": "Secondary Update",
                    "chunk_text": "Secondary update",
                },
                "combined_score": 0.88,
                "similarity": 0.88,
            },
            {
                "source": "confluence",
                "source_id": "CONF-1",
                "source_display": "CONF-1",
                "content": "Checklist",
                "metadata": {
                    "title": "Checklist",
                    "chunk_text": "Checklist",
                },
                "combined_score": 0.86,
                "similarity": 0.86,
            },
        ]

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ) as mock_search_documents, patch(
            "chat.utils.rag.rerank_documents", return_value=documents
        ) as mock_rerank_documents:
            result = rag.generate_answer(company_id=5, chatbot_id=9, query="status")

        self.assertEqual(result["answer"], "Answer referencing [jira:PROJ-1] with details")
        self.assertEqual(result["reasoning_trace"]["selected_draft_index"], 1)
        self.assertEqual(
            result["drafts"][result["reasoning_trace"]["selected_draft_index"]]["raw_answer"],
            "Answer referencing [jira:PROJ-1] with details",
        )
        self.assertIn("consensus", result["reasoning_trace"])
        self.assertEqual(
            result["reasoning_trace"]["consensus"]["method"], "consensus_citations"
        )
        self.assertIn(
            "[jira:PROJ-1]",
            result["reasoning_trace"]["consensus"]["consensus_citations"],
        )
        self.assertEqual(mock_client.chat.completions.create.call_args.kwargs.get("n"), 3)
        mock_search_documents.assert_called()
        self.assertEqual(
            mock_search_documents.call_args_list[0].kwargs.get("query_embedding"),
            [0.1, 0.2, 0.3],
        )
        mock_rerank_documents.assert_called_once()
        rerank_call = mock_rerank_documents.call_args
        self.assertEqual(rerank_call.args[0], "status")
        self.assertEqual(len(rerank_call.args[1]), len(documents))

    @override_settings(
        OPENAI_API_KEY="test-key",
        RAG_LOW_CONFIDENCE_THRESHOLD=0.95,
        RAG_LOW_CONFIDENCE_DRAFT_COUNT=2,
    )
    def test_generate_answer_uses_judge_ranking_when_available(self):
        mock_client = Mock()
        mock_choices = [
            SimpleNamespace(
                message=SimpleNamespace(content="First attempt without much detail")
            ),
            SimpleNamespace(
                message=SimpleNamespace(content="Improved answer referencing [jira:PROJ-1]")
            ),
        ]
        mock_client.chat.completions.create.return_value = SimpleNamespace(choices=mock_choices)

        documents = [
            {
                "source": "jira",
                "source_id": "PROJ-1",
                "source_display": "PROJ-1",
                "content": "Update",
                "metadata": {
                    "title": "Issue title",
                    "chunk_text": "Summary of the fix",
                },
                "similarity": 0.4,
            }
        ]

        judge_response = {
            "rankings": [
                {"index": 1, "score": 0.92, "feedback": "Cites the source"},
                {"index": 0, "score": 0.35},
            ],
            "rewrite": "Consider adding mitigation details.",
        }

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ), patch("chat.utils.rag.rerank_documents", return_value=documents), patch(
            "chat.utils.rag._judge_answer_drafts", return_value=judge_response
        ) as mock_judge:
            result = rag.generate_answer(company_id=1, chatbot_id=2, query="question?")

        mock_judge.assert_called_once()
        self.assertEqual(result["answer"], "Improved answer referencing [jira:PROJ-1]")
        self.assertEqual(result["reasoning_trace"]["evaluation_method"], "llm_judge")
        self.assertIn("judge", result["reasoning_trace"])
        self.assertEqual(
            result["reasoning_trace"]["judge"]["rankings"][0]["index"],
            1,
        )
        self.assertIn("rewrite", result["reasoning_trace"]["judge"])
        self.assertIn("judge_score", result["drafts"][1])
        self.assertEqual(result["drafts"][1]["judge_score"], 0.92)
        self.assertEqual(result["drafts"][1]["answer"], result["answer"])

    @override_settings(
        OPENAI_API_KEY="test-key",
        RAG_LOW_CONFIDENCE_THRESHOLD=0.95,
        RAG_LOW_CONFIDENCE_DRAFT_COUNT=2,
    )
    def test_generate_answer_falls_back_when_judge_errors(self):
        mock_client = Mock()
        mock_choices = [
            SimpleNamespace(
                message=SimpleNamespace(content="Answer with citation [jira:PROJ-1]")
            ),
            SimpleNamespace(message=SimpleNamespace(content="Answer without citation")),
        ]
        mock_client.chat.completions.create.return_value = SimpleNamespace(choices=mock_choices)

        documents = [
            {
                "source": "jira",
                "source_id": "PROJ-1",
                "source_display": "PROJ-1",
                "content": "Update",
                "metadata": {
                    "title": "Issue title",
                    "chunk_text": "Summary of the fix",
                },
                "similarity": 0.4,
            }
        ]

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ), patch("chat.utils.rag.rerank_documents", return_value=documents), patch(
            "chat.utils.rag._judge_answer_drafts", side_effect=RuntimeError("judge failed")
        ) as mock_judge:
            result = rag.generate_answer(company_id=1, chatbot_id=2, query="question?")

        mock_judge.assert_called_once()
        self.assertEqual(result["answer"], "Answer with citation [jira:PROJ-1]")
        self.assertEqual(
            result["reasoning_trace"]["evaluation_method"], "heuristic_citation_scoring"
        )
        self.assertIn("judge_error", result["reasoning_trace"])
        self.assertEqual(result["reasoning_trace"]["heuristic_selected_index"], 0)

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
    def test_low_confidence_drafts_prefer_cited_response(self):
        mock_client = Mock()
        mock_choices = [
            SimpleNamespace(message=SimpleNamespace(content="I don't know.")),
            SimpleNamespace(
                message=SimpleNamespace(
                    content="The incident has been resolved [jira:PROJ-2]"
                )
            ),
            SimpleNamespace(
                message=SimpleNamespace(
                    content="Resolution confirmed [jira:PROJ-2]"
                )
            ),
        ]
        mock_response = SimpleNamespace(choices=mock_choices)
        mock_client.chat.completions.create.return_value = mock_response

        documents = [
            {
                "source": "jira",
                "source_id": "PROJ-2",
                "source_display": "PROJ-2",
                "content": "Resolution summary",
                "metadata": {
                    "title": "Resolution summary",
                    "chunk_text": "Ticket resolved successfully",
                    "chunk_index": 0,
                    "chunk_count": 1,
                },
                "similarity": 0.2,
                "combined_score": 0.2,
            }
        ]

        with patch("chat.utils.rag.get_openai_client", return_value=mock_client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ), patch("chat.utils.rag.rerank_documents", return_value=documents):
            result = rag.generate_answer(
                company_id=1, chatbot_id=2, query="Give me the latest status"
            )

        self.assertTrue(result["reasoning_trace"]["low_confidence_mode"])
        self.assertGreaterEqual(result["confidence"], result["retrieval_confidence"])
        self.assertIn("[jira:PROJ-2]", result["answer"])
        self.assertEqual(result["drafts"][0]["contains_uncertainty"], True)
        self.assertGreater(
            result["drafts"][1]["score"],
            result["drafts"][0]["score"],
        )
        draft_call_n = next(
            (
                call.kwargs.get("n")
                for call in mock_client.chat.completions.create.call_args_list
                if call.kwargs.get("n") is not None
            ),
            None,
        )
        self.assertEqual(draft_call_n, 3)

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
