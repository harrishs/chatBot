import os
from unittest.mock import patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("ENCRYPTION_KEY", "wvRwBW8Y7-P2eFoRhqNRdbi8ZjsIvkTCmFll1xQ3hl8=")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DJANGO_SECRET_KEY", "unit-test-secret")

django.setup()

from django.test import TestCase, override_settings  # noqa: E402

from chat.models import ChatBotInstance, Company, Document  # noqa: E402
from chat.utils.embeddings import rerank_documents, save_document, search_documents  # noqa: E402


class SearchDocumentsRankingTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Search Co")
        self.chatbot = ChatBotInstance.objects.create(company=self.company, name="Search Bot")
        self.other_chatbot = ChatBotInstance.objects.create(company=self.company, name="Other Bot")

        self.primary_embedding = self._unit_vector(0)

        self.jira_doc = Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="jira_issue",
            source_id="JIRA-1",
            content="Release plan approved",
            embedding=self.primary_embedding,
        )
        self.confluence_doc = Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="confluence",
            source_id="CONF-1",
            content="Release plan release plan with detailed schedule",
            embedding=self.primary_embedding,
        )
        self.github_doc = Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="github",
            source_id="src/app.py",
            content="Implementation details without planning notes",
            embedding=self.primary_embedding,
        )
        Document.objects.create(
            company=self.company,
            chatbot=self.other_chatbot,
            source="jira_issue",
            source_id="JIRA-2",
            content="Unrelated issue",
            embedding=self.primary_embedding,
        )

    def _unit_vector(self, index):
        vector = [0.0] * 1536
        vector[index] = 1.0
        return vector

    @patch("chat.utils.embeddings.embed_text")
    def test_combined_scoring_prefers_lexical_matches(self, mock_embed_text):
        mock_embed_text.return_value = self.primary_embedding

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="release plan",
            top_k=3,
        )

        ordered_ids = [result["source_id"] for result in results]
        self.assertEqual(ordered_ids, ["CONF-1", "JIRA-1", "src/app.py"])
        self.assertGreater(results[0]["combined_score"], results[1]["combined_score"])
        self.assertGreaterEqual(results[1]["combined_score"], results[2]["combined_score"])

    @patch("chat.utils.embeddings.embed_text")
    def test_search_documents_respects_source_filter(self, mock_embed_text):
        mock_embed_text.return_value = self.primary_embedding

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="release plan",
            top_k=5,
            sources=["jira_issue"],
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], self.jira_doc.id)
        self.assertTrue(all(result["source"] == "jira_issue" for result in results))


class RerankDocumentsTests(TestCase):
    @override_settings(OPENAI_RERANK_EMBEDDING_MODEL="text-embedding-3-large")
    @patch("chat.utils.embeddings.embed_text")
    def test_rerank_documents_prioritizes_high_fidelity_similarity(self, mock_embed_text):
        query = "release schedule"

        documents = [
            {"id": 1, "source_id": "CONF-1", "content": "release schedule overview"},
            {"id": 2, "source_id": "GH-1", "content": "implementation notes"},
            {"id": 3, "source_id": "JIRA-9", "content": "schedule blockers"},
        ]

        vector_map = {
            (query, "text-embedding-3-large"): [1.0, 0.0],
            ("release schedule overview", "text-embedding-3-large"): [1.0, 0.1],
            ("implementation notes", "text-embedding-3-large"): [0.2, 1.0],
            ("schedule blockers", "text-embedding-3-large"): [0.8, 0.6],
        }

        def side_effect(text, *, model=None):
            key = (text, model or "text-embedding-3-small")
            if key in vector_map:
                return vector_map[key]
            return [1.0] + [0.0] * 1535

        mock_embed_text.side_effect = side_effect

        reranked = rerank_documents(query, documents)

        ordered_ids = [doc["source_id"] for doc in reranked]
        self.assertEqual(ordered_ids, ["CONF-1", "JIRA-9", "GH-1"])
        self.assertIsNotNone(reranked[0]["rerank_score"])
        self.assertGreater(reranked[0]["rerank_score"], reranked[1]["rerank_score"])


class DocumentChunkingMetadataTests(TestCase):
    def setUp(self):
        self.company = Company.objects.create(name="Metadata Co")
        self.chatbot = ChatBotInstance.objects.create(company=self.company, name="Metadata Bot")

    def _fake_embedding(self, text, *, model=None):
        vector = [0.0] * 1536
        lowered = (text or "").lower()
        markers = {
            "guide to setup": 0,
            "docs/guide.md": 1,
            "heading one": 2,
            "second sentence": 3,
        }
        for token, index in markers.items():
            if token in lowered:
                vector[index] = 1.0
        return vector

    @patch("chat.utils.embeddings.embed_text")
    def test_query_matches_structured_metadata(self, mock_embed_text):
        mock_embed_text.side_effect = self._fake_embedding

        content = "# Heading One\nThis guide explains setup steps in detail."
        docs = save_document(
            company=self.company,
            chatbot=self.chatbot,
            source="confluence",
            source_id="guide-1",
            content=content,
            metadata={"title": "Guide to Setup", "path": "docs/guide.md"},
        )

        self.assertEqual(len(docs), 1)
        stored_doc = docs[0]
        self.assertEqual(stored_doc.metadata.get("title"), "Guide to Setup")
        self.assertEqual(stored_doc.metadata.get("path"), "docs/guide.md")
        self.assertEqual(stored_doc.metadata.get("section_heading"), "Heading One")

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="Guide to Setup",
            top_k=3,
        )

        self.assertTrue(results)
        self.assertEqual(results[0]["source_id"], stored_doc.source_id)
        self.assertEqual(results[0]["metadata"].get("title"), "Guide to Setup")

    @patch("chat.utils.embeddings.embed_text")
    def test_segments_include_overlap_for_context(self, mock_embed_text):
        mock_embed_text.side_effect = self._fake_embedding

        content = (
            "# Heading One\n"
            "First sentence introduces the topic.\n"
            "Second sentence provides additional detail.\n\n"
            "Third sentence transitions to examples.\n"
            "Fourth sentence concludes the discussion."
        )

        docs = save_document(
            company=self.company,
            chatbot=self.chatbot,
            source="confluence",
            source_id="guide-2",
            content=content,
            metadata={"title": "Guide to Setup", "path": "docs/guide.md"},
            max_tokens=20,
            overlap_tokens=6,
        )

        self.assertGreaterEqual(len(docs), 2)
        for idx, doc in enumerate(docs):
            self.assertEqual(doc.metadata.get("chunk_index"), idx)
            self.assertEqual(doc.metadata.get("chunk_count"), len(docs))
            self.assertEqual(doc.metadata.get("section_heading"), "Heading One")

        def extract_body(text):
            parts = text.split("\n\n", 1)
            return parts[1] if len(parts) > 1 else parts[0]

        bodies = [extract_body(doc.content) for doc in docs]

        self.assertIn("Second sentence provides additional detail.", bodies[0])
        self.assertTrue(
            any("Second sentence provides additional detail." in body for body in bodies[1:]),
            "Overlapping segment should retain context from prior chunk",
        )
