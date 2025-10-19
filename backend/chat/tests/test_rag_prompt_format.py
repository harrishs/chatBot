from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings

from chat.utils import rag


class DummyChatClient:
    def __init__(self, response_text: str):
        self.response_text = response_text
        self.captured_kwargs = None
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self._create)
        )

    def _create(self, **kwargs):
        self.captured_kwargs = kwargs
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=self.response_text)
                )
            ]
        )


@override_settings(OPENAI_API_KEY="test-key", MIGRATION_MODULES={"chat": None})
class GenerateAnswerPromptTests(TestCase):
    def _run_generate_answer(self, documents, response_text="Mock answer"):
        client = DummyChatClient(response_text)
        with patch("chat.utils.rag.get_openai_client", return_value=client), patch(
            "chat.utils.rag.search_documents", return_value=documents
        ), patch("chat.utils.rag.rerank_documents", side_effect=lambda query, docs: docs):
            result = rag.generate_answer(
                company_id=1,
                chatbot_id=1,
                query="What does the document say?",
            )

        messages = client.captured_kwargs["messages"]
        system_prompt = messages[0]["content"]
        user_prompt = messages[1]["content"]
        return result, system_prompt, user_prompt

    def test_prompt_includes_git_snippet_and_path_metadata(self):
        snippet = "```python\ndef example():\n    return True\n```"
        documents = [
            {
                "id": 1,
                "source": "git",
                "source_id": "repo/backend/app.py",
                "source_display": "repo/backend/app.py",
                "similarity": 0.72,
                "combined_score": 0.8,
                "metadata": {
                    "title": "Example Module",
                    "path": "repo/backend/app.py",
                    "section_heading": "Usage",
                    "source_url": "https://git.example/repo/backend/app.py",
                    "chunk_index": 0,
                    "chunk_count": 2,
                    "chunk_tokens": 5,
                    "chunk_char_count": len(snippet),
                    "chunk_text": snippet,
                },
            }
        ]

        response_text = "Here is what I found [git:repo/backend/app.py]"
        result, system_prompt, user_prompt = self._run_generate_answer(
            documents, response_text
        )

        self.assertIn("[git:repo/backend/app.py]", user_prompt)
        self.assertIn("- Title: Example Module", user_prompt)
        self.assertIn("- Path: repo/backend/app.py", user_prompt)
        self.assertIn("- Section: Usage", user_prompt)
        self.assertIn(f"Snippet:\n{snippet}", user_prompt)
        self.assertIn("short, sanitized code excerpts", system_prompt)
        self.assertIn("short, sanitized code excerpts", user_prompt)

        source_metadata = result["sources"][0]
        self.assertEqual(source_metadata["snippet"], snippet)
        self.assertEqual(source_metadata["chunk_text"], snippet)

    def test_prompt_includes_confluence_snippet_and_space_metadata(self):
        snippet = "This playbook explains the deployment process."
        documents = [
            {
                "id": 2,
                "source": "confluence",
                "source_id": "ENG-123",
                "source_display": "ENG-123",
                "similarity": 0.81,
                "combined_score": 0.85,
                "metadata": {
                    "title": "Release Playbook",
                    "space_key": "ENG",
                    "section_heading": "Deployments",
                    "source_url": "https://confluence.example.com/pages/ENG-123",
                    "chunk_index": 1,
                    "chunk_count": 3,
                    "chunk_tokens": 7,
                    "chunk_char_count": len(snippet),
                    "chunk_text": snippet,
                },
            }
        ]

        response_text = "Consult the documentation [confluence:ENG-123]"
        result, _, user_prompt = self._run_generate_answer(documents, response_text)

        self.assertIn("[confluence:ENG-123]", user_prompt)
        self.assertIn("- Title: Release Playbook", user_prompt)
        self.assertIn("- Space: ENG", user_prompt)
        self.assertIn("- Chunk: 2 of 3", user_prompt)
        self.assertIn(f"Snippet:\n{snippet}", user_prompt)

        source_metadata = result["sources"][0]
        self.assertEqual(source_metadata["snippet"], snippet)
        self.assertEqual(source_metadata["chunk_text"], snippet)
