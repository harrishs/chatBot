import os
from types import SimpleNamespace
from typing import Dict, List, Tuple
from unittest.mock import patch

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
os.environ.setdefault("ENCRYPTION_KEY", "wvRwBW8Y7-P2eFoRhqNRdbi8ZjsIvkTCmFll1xQ3hl8=")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("DJANGO_SECRET_KEY", "unit-test-secret")

django.setup()

from django.test import SimpleTestCase, TestCase, override_settings  # noqa: E402

from chat.models import ChatBotInstance, Company, Document  # noqa: E402
from chat.utils import rag  # noqa: E402
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

    def _chat_client(self, response_text: str = "Acknowledged"):
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=response_text))]
        )

        def _create(**kwargs):
            return response

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=_create))
        )

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

    @override_settings(
        RAG_VECTOR_WEIGHT=0.2,
        RAG_WEBSEARCH_WEIGHT=0.6,
        RAG_TRIGRAM_WEIGHT=0.2,
    )
    @patch("chat.utils.embeddings.embed_text")
    def test_phrase_search_boosts_phrase_matches(self, mock_embed_text):
        mock_embed_text.return_value = self.primary_embedding

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="release plan",
            top_k=3,
        )

        self.assertEqual(results[0]["source_id"], "CONF-1")
        self.assertGreater(results[0]["websearch_score"], results[1]["websearch_score"])
        self.assertGreater(results[0]["combined_score"], results[1]["combined_score"])

    @override_settings(
        RAG_VECTOR_WEIGHT=0.1,
        RAG_WEBSEARCH_WEIGHT=0.3,
        RAG_TRIGRAM_WEIGHT=0.6,
    )
    @patch("chat.utils.embeddings.embed_text")
    def test_partial_token_queries_use_trigram_similarity(self, mock_embed_text):
        mock_embed_text.return_value = self.primary_embedding

        fuzzy_doc = Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="confluence",
            source_id="CONF-2",
            content="Project schedul updates and timeline",
            embedding=self.primary_embedding,
        )

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="schedul",
            top_k=3,
        )

        self.assertEqual(results[0]["source_id"], fuzzy_doc.source_id)
        self.assertGreater(results[0]["trigram_score"], results[1]["trigram_score"])
        self.assertGreater(results[0]["combined_score"], results[1]["combined_score"])

    @patch("chat.utils.embeddings.embed_text")
    def test_feedback_documents_are_returned_with_custom_display(self, mock_embed_text):
        mock_embed_text.return_value = self.primary_embedding

        feedback_comment = "Users want more onboarding guidance"
        feedback_doc = Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="feedback",
            source_id="feedback-42",
            content=feedback_comment,
            embedding=self.primary_embedding,
            metadata={"comment": feedback_comment, "source_display": "feedback-42"},
        )

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="onboarding feedback",
            top_k=5,
        )

        returned = next(result for result in results if result["id"] == feedback_doc.id)
        self.assertEqual(returned["source"], "feedback")
        self.assertEqual(returned["source_display"], "feedback-42")
        self.assertEqual(returned["metadata"].get("comment"), feedback_comment)

    @patch("chat.utils.embeddings.embed_text")
    def test_unmatched_query_has_zero_lexical_scores(self, mock_embed_text):
        mock_embed_text.return_value = self.primary_embedding

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="nonexistent phrase",
            top_k=2,
        )

        for result in results:
            self.assertEqual(result["websearch_score"], 0.0)
            self.assertLess(result["trigram_score"], 0.05)

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

    @override_settings(RAG_SEARCH_MIN_SCORE=0.8)
    @patch("chat.utils.embeddings.record_retrieval_fallback_event")
    @patch("chat.utils.embeddings.embed_text")
    def test_low_score_triggers_search_fallback(
        self,
        mock_embed_text,
        mock_record_event,
    ):
        mock_embed_text.return_value = self.primary_embedding

        self.jira_doc.content = "Miscellaneous status update"
        self.jira_doc.embedding = self._unit_vector(10)
        self.jira_doc.save(update_fields=["content", "embedding"])

        strong_doc = Document.objects.create(
            company=self.company,
            chatbot=self.chatbot,
            source="confluence",
            source_id="CONF-STRONG",
            content="Comprehensive release plan with milestones",
            embedding=self.primary_embedding,
        )

        results = search_documents(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="release plan",
            top_k=1,
            sources=["jira_issue"],
        )

        self.assertGreaterEqual(len(results), 1)
        self.assertEqual(results[0]["source_id"], strong_doc.source_id)
        self.assertAlmostEqual(results[0]["normalized_score"], 1.0)
        mock_record_event.assert_called_once()
        details = mock_record_event.call_args.kwargs.get("details")
        self.assertIsInstance(details, dict)
        self.assertGreater(details.get("final_best", 0.0), details.get("primary_best", 0.0))

    @override_settings(OPENAI_API_KEY="test-key", MIGRATION_MODULES={"chat": None})
    @patch("chat.utils.rag.rerank_documents", side_effect=lambda query, docs: docs)
    @patch("chat.utils.rag.search_documents")
    @patch("chat.utils.rag.get_openai_client")
    def test_jira_specific_question_limits_to_jira_sources(
        self,
        mock_get_openai_client,
        mock_search_documents,
        mock_rerank_documents,
    ):
        mock_get_openai_client.return_value = self._chat_client(
            "Status is up to date [jira:JIRA-1]"
        )

        jira_documents = [
            {
                "id": 101,
                "source": "jira",
                "source_id": "JIRA-1",
                "source_display": "JIRA-1",
                "combined_score": 0.92,
                "similarity": 0.92,
                "metadata": {"chunk_text": "Ticket status update."},
            }
        ]

        mock_search_documents.side_effect = [jira_documents, jira_documents]

        result = rag.generate_answer(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="What's the status of ticket JIRA-1?",
        )

        self.assertGreaterEqual(len(mock_search_documents.call_args_list), 2)
        targeted_kwargs = mock_search_documents.call_args_list[0].kwargs
        self.assertEqual(targeted_kwargs.get("sources"), ["jira_issue", "jira_comment"])
        fallback_kwargs = mock_search_documents.call_args_list[-1].kwargs
        self.assertIsNone(fallback_kwargs.get("sources"))

        trace = result.get("reasoning_trace", {})
        self.assertIn(["jira_issue", "jira_comment"], trace.get("retrieval_source_plan", []))
        self.assertTrue(result["sources"])
        self.assertTrue(all(entry["source"] == "jira" for entry in result["sources"]))

    @override_settings(OPENAI_API_KEY="test-key", MIGRATION_MODULES={"chat": None})
    @patch("chat.utils.rag.rerank_documents", side_effect=lambda query, docs: docs)
    @patch("chat.utils.rag.search_documents")
    @patch("chat.utils.rag.get_openai_client")
    def test_mixed_question_considers_all_sources(
        self,
        mock_get_openai_client,
        mock_search_documents,
        mock_rerank_documents,
    ):
        mock_get_openai_client.return_value = self._chat_client(
            "Here is what I found [jira:JIRA-1] [confluence:CONF-1]"
        )

        jira_documents = [
            {
                "id": 201,
                "source": "jira",
                "source_id": "JIRA-1",
                "source_display": "JIRA-1",
                "combined_score": 0.92,
                "similarity": 0.92,
                "metadata": {"chunk_text": "Ticket status update."},
            }
        ]
        confluence_documents = [
            {
                "id": 202,
                "source": "confluence",
                "source_id": "CONF-1",
                "source_display": "CONF-1",
                "combined_score": 0.88,
                "similarity": 0.88,
                "metadata": {"chunk_text": "Release plan summary."},
            }
        ]

        mock_search_documents.side_effect = [
            jira_documents,
            confluence_documents,
            jira_documents + confluence_documents,
        ]

        result = rag.generate_answer(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="Compare Jira ticket JIRA-1 with the Confluence release page.",
        )

        self.assertEqual(len(mock_search_documents.call_args_list), 3)
        first_kwargs = mock_search_documents.call_args_list[0].kwargs
        second_kwargs = mock_search_documents.call_args_list[1].kwargs
        fallback_kwargs = mock_search_documents.call_args_list[2].kwargs

        self.assertEqual(first_kwargs.get("sources"), ["jira_issue", "jira_comment"])
        self.assertEqual(second_kwargs.get("sources"), ["confluence"])
        self.assertIsNone(fallback_kwargs.get("sources"))

        trace = result.get("reasoning_trace", {})
        plan = trace.get("retrieval_source_plan", [])
        self.assertIn(["jira_issue", "jira_comment"], plan)
        self.assertIn(["confluence"], plan)

        sources = {entry["source"] for entry in result["sources"]}
        self.assertIn("jira", sources)
        self.assertIn("confluence", sources)

    @override_settings(OPENAI_API_KEY="test-key", MIGRATION_MODULES={"chat": None})
    @patch("chat.utils.rag.embed_text", return_value=[0.1])
    @patch("chat.utils.rag.rerank_documents", side_effect=lambda query, docs: docs)
    @patch("chat.utils.rag.search_documents")
    @patch("chat.utils.rag.get_openai_client")
    def test_feedback_queries_prioritize_feedback_sources(
        self,
        mock_get_openai_client,
        mock_search_documents,
        mock_rerank_documents,
        mock_embed_text,
    ):
        mock_get_openai_client.return_value = self._chat_client(
            "Considering recent user feedback [feedback:feedback-1]"
        )

        feedback_metadata = {
            "chunk_text": "Comment: Users reported confusion during onboarding.",
            "comment": "Users reported confusion during onboarding.",
        }
        feedback_documents = [
            {
                "id": 301,
                "source": "feedback",
                "source_id": "feedback-1",
                "source_display": "feedback-1",
                "combined_score": 0.9,
                "similarity": 0.9,
                "metadata": feedback_metadata,
            }
        ]

        mock_search_documents.side_effect = [feedback_documents, feedback_documents]

        result = rag.generate_answer(
            company_id=self.company.id,
            chatbot_id=self.chatbot.id,
            query="What does the feedback say about onboarding?",
        )

        self.assertGreaterEqual(len(mock_search_documents.call_args_list), 2)
        first_kwargs = mock_search_documents.call_args_list[0].kwargs
        self.assertEqual(first_kwargs.get("sources"), ["feedback"])
        fallback_kwargs = mock_search_documents.call_args_list[-1].kwargs
        self.assertIsNone(fallback_kwargs.get("sources"))

        trace = result.get("reasoning_trace", {})
        self.assertIn(["feedback"], trace.get("retrieval_source_plan", []))

        sources = {entry["source"] for entry in result["sources"]}
        self.assertIn("feedback", sources)
        self.assertTrue(
            any(
                "onboarding" in (entry.get("snippet") or "")
                for entry in result["sources"]
                if entry.get("source") == "feedback"
            )
        )


class RerankDocumentsTests(TestCase):
    @override_settings(
        OPENAI_RERANK_MODEL="gpt-4o-mini",
        RAG_RERANK_TOP_N=3,
    )
    @patch("chat.utils.embeddings.embed_text")
    @patch("chat.utils.embeddings._call_cross_encoder_reranker")
    def test_rerank_documents_uses_cross_encoder_scores(
        self,
        mock_reranker,
        mock_embed_text,
    ):
        query = "release schedule"

        documents = [
            {"id": 1, "source_id": "CONF-1", "content": "release schedule overview"},
            {"id": 2, "source_id": "GH-1", "content": "implementation notes"},
            {"id": 3, "source_id": "JIRA-9", "content": "schedule blockers"},
        ]

        mock_reranker.return_value = {"2": 0.91, "1": 0.75}
        mock_embed_text.side_effect = AssertionError("embed_text should not be called when reranker succeeds")

        reranked = rerank_documents(query, documents)

        ordered_ids = [doc["source_id"] for doc in reranked]
        self.assertEqual(ordered_ids, ["GH-1", "CONF-1", "JIRA-9"])
        self.assertAlmostEqual(reranked[0]["rerank_score"], 0.91)
        self.assertAlmostEqual(reranked[1]["rerank_score"], 0.75)
        mock_reranker.assert_called_once()

    @override_settings(
        OPENAI_RERANK_MODEL="gpt-4o-mini",
        OPENAI_RERANK_EMBEDDING_MODEL="",
    )
    @patch("chat.utils.embeddings._call_cross_encoder_reranker", side_effect=RuntimeError("boom"))
    def test_rerank_documents_falls_back_to_original_order_when_reranker_unavailable(
        self,
        mock_reranker,
    ):
        documents = [
            {"id": 1, "source_id": "CONF-1", "content": "release schedule overview"},
            {"id": 2, "source_id": "GH-1", "content": "implementation notes"},
        ]

        reranked = rerank_documents("release schedule", documents)

        self.assertEqual([doc["source_id"] for doc in reranked], ["CONF-1", "GH-1"])
        self.assertTrue(all(doc["rerank_score"] is None for doc in reranked))

    @override_settings(
        OPENAI_RERANK_MODEL="",
        OPENAI_RERANK_EMBEDDING_MODEL="text-embedding-3-large",
        RAG_RERANK_TOP_N=5,
    )
    @patch("chat.utils.embeddings.embed_text")
    def test_rerank_documents_caches_high_fidelity_embeddings_and_invalidates(
        self,
        mock_embed_text,
    ):
        company = Company.objects.create(name="Rerank Co")
        chatbot = ChatBotInstance.objects.create(company=company, name="Cache Bot")

        vectors: Dict[Tuple[str, str], List[float]] = {}

        def vector_for(key):
            if key not in vectors:
                index = len(vectors) % 1536
                vec = [0.0] * 1536
                vec[index] = 1.0
                vectors[key] = vec
            return vectors[key]

        call_counts: Dict[Tuple[str, str], int] = {}

        def fake_embed(text, *, model=None):
            key = (text, model or "default")
            call_counts[key] = call_counts.get(key, 0) + 1
            if model == "text-embedding-3-large":
                return list(vector_for(key))
            return [1.0] + [0.0] * 1535

        mock_embed_text.side_effect = fake_embed

        docs = save_document(
            company=company,
            chatbot=chatbot,
            source="confluence",
            source_id="doc-1",
            content="Release schedule overview",
        )

        self.assertEqual(len(docs), 1)
        stored_doc = docs[0]

        doc_payload = [
            {
                "id": stored_doc.id,
                "source_id": stored_doc.source_id,
                "content": stored_doc.content,
            }
        ]

        first_rerank = rerank_documents("release schedule", doc_payload)
        self.assertIsNotNone(first_rerank[0]["rerank_score"])

        key = (stored_doc.content, "text-embedding-3-large")
        self.assertEqual(call_counts[key], 1, "Document should be embedded once")

        second_rerank = rerank_documents("release schedule", doc_payload)
        self.assertIsNotNone(second_rerank[0]["rerank_score"])
        self.assertEqual(call_counts[key], 1, "Cached embedding should be reused without new calls")

        save_document(
            company=company,
            chatbot=chatbot,
            source="confluence",
            source_id="doc-1",
            content="Updated release schedule overview",
        )

        updated_doc = Document.objects.get(id=stored_doc.id)
        updated_payload = [
            {
                "id": updated_doc.id,
                "source_id": updated_doc.source_id,
                "content": updated_doc.content,
            }
        ]

        rerank_documents("release schedule", updated_payload)

        updated_key = (updated_doc.content, "text-embedding-3-large")
        self.assertEqual(call_counts[updated_key], 1, "Embedding should be recomputed after invalidation")

    @override_settings(
        OPENAI_RERANK_MODEL="",
        OPENAI_RERANK_EMBEDDING_MODEL="",
        OPENAI_EMBEDDING_MODEL="text-embedding-3-small",
        RAG_RERANK_TOP_N=2,
    )
    @patch("chat.utils.embeddings.embed_text")
    def test_rerank_documents_falls_back_to_primary_embedding_model(
        self,
        mock_embed_text,
    ):
        query = "release schedule"

        embeddings = {
            query: [1.0, 0.0],
            "release schedule overview": [1.0, 0.0],
            "implementation notes": [0.0, 1.0],
        }

        def fake_embed(text, *, model=None):
            self.assertEqual(model, "text-embedding-3-small")
            vector = embeddings.get(text)
            if vector is None:
                self.fail(f"Unexpected text embedded: {text}")
            return list(vector)

        mock_embed_text.side_effect = fake_embed

        documents = [
            {"id": None, "source_id": "CONF-1", "content": "release schedule overview"},
            {"id": None, "source_id": "GH-1", "content": "implementation notes"},
        ]

        reranked = rerank_documents(query, documents)

        self.assertEqual([doc["source_id"] for doc in reranked], ["CONF-1", "GH-1"])
        self.assertAlmostEqual(reranked[0]["rerank_score"], 1.0)
        self.assertAlmostEqual(reranked[1]["rerank_score"], 0.0)
        self.assertTrue(all(doc["rerank_score"] is not None for doc in reranked))


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
        self.assertIn("This guide explains setup steps", stored_doc.metadata.get("chunk_text"))
        self.assertGreater(stored_doc.metadata.get("chunk_tokens", 0), 0)

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
            self.assertTrue(doc.metadata.get("chunk_text"))
            self.assertGreater(doc.metadata.get("chunk_tokens", 0), 0)

        def extract_body(text):
            parts = text.split("\n\n", 1)
            return parts[1] if len(parts) > 1 else parts[0]

        bodies = [extract_body(doc.content) for doc in docs]

        self.assertIn("Second sentence provides additional detail.", bodies[0])
        self.assertTrue(
            any("Second sentence provides additional detail." in body for body in bodies[1:]),
            "Overlapping segment should retain context from prior chunk",
        )


class RetrievalConfidenceScoringTests(SimpleTestCase):
    def test_retrieval_confidence_prefers_normalized_scores(self):
        high_normalized = [
            {"normalized_score": 0.9, "combined_score": 0.2},
            {"normalized_score": 0.8, "combined_score": 0.1},
        ]
        mixed_scores = [
            {"normalized_score": 0.4, "combined_score": 0.95},
            {"combined_score": 0.3},
        ]

        high_confidence = rag._compute_retrieval_confidence(high_normalized)
        mixed_confidence = rag._compute_retrieval_confidence(mixed_scores)

        self.assertGreater(high_confidence, mixed_confidence)

    def test_retrieval_confidence_falls_back_when_normalized_missing(self):
        documents = [
            {"combined_score": 0.8},
            {"similarity": 0.6},
        ]

        confidence = rag._compute_retrieval_confidence(documents)

        expected = (0.7 * 0.8) + (0.3 * 0.6)
        self.assertAlmostEqual(confidence, expected)
