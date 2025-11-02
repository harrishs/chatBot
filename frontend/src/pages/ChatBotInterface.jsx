import { useParams } from "react-router-dom";
import { useState, useMemo } from "react";
import api from "../api/axios";
import { buildChatRequest } from "../utils/chatHistory.js";
import { processFeedbackCommand } from "../utils/feedback.js";
import SourceChip from "../components/SourceChip.jsx";
import ConfidenceBadge from "../components/ConfidenceBadge.jsx";
import "./ChatBotInterface.css";

function ChatBotPage({ apiClient = api, chatbotId: overrideId }) {
        const params = useParams();
        const id = overrideId ?? params.id;
        const [query, setQuery] = useState("");
        const [messages, setMessages] = useState([]);
        const [notice, setNotice] = useState("");

        const hasPendingAssistant = useMemo(
                () => messages.some((message) => message.role === "assistant" && message.pending),
                [messages],
        );

        const executeChatRequest = async ({ requestId, queryText, historyMessages }) => {
                const { url, body } = buildChatRequest({
                        id,
                        messages: historyMessages,
                        query: queryText,
                });

                try {
                        const res = await apiClient.post(url, body);
                        const data = res?.data ?? {};
                        const {
                                answer = "",
                                sources,
                                citations,
                                confidence,
                                confidence_score: confidenceScore,
                                related_questions: relatedQuestions,
                        } = data;

                        const resolvedSources = Array.isArray(sources) && sources.length > 0
                                ? sources
                                : Array.isArray(citations) && citations.length > 0
                                ? citations
                                : [];

                        const resolvedConfidence =
                                confidence !== undefined && confidence !== null
                                        ? confidence
                                        : confidenceScore ?? null;

                        setMessages((prev) =>
                                prev.map((message) =>
                                        message.role === "assistant" && message.requestId === requestId
                                                ? {
                                                          ...message,
                                                          content: answer,
                                                          pending: false,
                                                          error: false,
                                                          errorMessage: undefined,
                                                          sources: resolvedSources,
                                                          confidence: resolvedConfidence,
                                                          relatedQuestions: Array.isArray(relatedQuestions)
                                                                  ? relatedQuestions
                                                                  : [],
                                                          responseData: data,
                                                  }
                                                : message,
                                ),
                        );
                } catch (err) {
                        console.error("Chat error:", err);
                        setMessages((prev) =>
                                prev.map((message) =>
                                        message.role === "assistant" && message.requestId === requestId
                                                ? {
                                                          ...message,
                                                          pending: false,
                                                          error: true,
                                                          errorMessage:
                                                                  "Unable to retrieve a response. Please try again.",
                                                  }
                                                : message,
                                ),
                        );
                }
        };

        const sendQuery = async () => {
                const trimmedQuery = query.trim();
                if (!trimmedQuery) return;

                const handled = await processFeedbackCommand({
                        trimmedQuery,
                        apiClient,
                        chatbotId: id,
                        setNotice,
                        setQuery,
                });
                if (handled) {
                        return;
                }

                setNotice("");

                const requestId = `${Date.now()}-${Math.random().toString(36).slice(2)}`;

                const userMessage = {
                        role: "user",
                        content: trimmedQuery,
                        requestId,
                        timestamp: Date.now(),
                };
                const assistantPlaceholder = {
                        role: "assistant",
                        content: "",
                        requestId,
                        pending: true,
                        sources: [],
                        confidence: null,
                        relatedQuestions: [],
                };

                const updatedMessages = [...messages, userMessage, assistantPlaceholder];
                setMessages(updatedMessages);
                setQuery("");

                await executeChatRequest({
                        requestId,
                        queryText: trimmedQuery,
                        historyMessages: updatedMessages,
                });
        };

        const retryMessage = async (requestId) => {
                const userMessage = messages.find(
                        (message) => message.role === "user" && message.requestId === requestId,
                );

                if (!userMessage) {
                        return;
                }

                const refreshedMessages = messages.map((message) =>
                        message.role === "assistant" && message.requestId === requestId
                                ? {
                                          ...message,
                                          pending: true,
                                          error: false,
                                          errorMessage: undefined,
                                  }
                                : message,
                );

                setMessages(refreshedMessages);

                await executeChatRequest({
                        requestId,
                        queryText: userMessage.content ?? "",
                        historyMessages: refreshedMessages,
                });
        };

        return (
                <div className="chatbot-page">
                        <h2>Chat with Bot {id}</h2>
                        {notice ? (
                                <div role="status" className="chatbot-notice">
                                        {notice}
                                </div>
                        ) : null}
                        <div className="chatbot-messages">
                                {messages.length === 0 ? (
                                        <div style={{ color: "#6b7280" }}>Ask a question to get started.</div>
                                ) : null}
                                {messages.map((message, index) => {
                                        const key = message.requestId
                                                ? `${message.requestId}-${message.role}`
                                                : `${message.role}-${index}`;
                                        const isAssistant = message.role === "assistant";

                                        return (
                                                <div
                                                        key={key}
                                                        className={`chatbot-message${
                                                                isAssistant ? " chatbot-message--assistant" : ""
                                                        }`}
                                                >
                                                        <div className="chatbot-message__header">
                                                                <span>{isAssistant ? "Assistant" : "User"}</span>
                                                        </div>
                                                        <div className="chatbot-message__content">
                                                                {isAssistant ? (
                                                                        message.pending ? (
                                                                                <span className="chatbot-pending">
                                                                                        <span
                                                                                                className="chatbot-spinner"
                                                                                                aria-hidden="true"
                                                                                        />
                                                                                        <span>Thinking...</span>
                                                                                </span>
                                                                        ) : message.error ? (
                                                                                <div>
                                                                                        <div className="chatbot-error">
                                                                                                {message.errorMessage}
                                                                                        </div>
                                                                                        <button
                                                                                                type="button"
                                                                                                className="chatbot-retry-button"
                                                                                                onClick={() => retryMessage(message.requestId)}
                                                                                        >
                                                                                                Retry
                                                                                        </button>
                                                                                </div>
                                                                        ) : (
                                                                                message.content || (
                                                                                        <span style={{ color: "#6b7280" }}>
                                                                                                No response provided.
                                                                                        </span>
                                                                                )
                                                                        )
                                                                ) : (
                                                                        message.content
                                                                )}
                                                        </div>
                                                        {isAssistant && !message.pending && !message.error ? (
                                                                <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
                                                                        {message.sources && message.sources.length > 0 ? (
                                                                                <div className="chatbot-sources">
                                                                                        {message.sources.map((source, index) => {
                                                                                                const sourceKey =
                                                                                                        (source &&
                                                                                                                (source.id ||
                                                                                                                        source.url ||
                                                                                                                        source.link ||
                                                                                                                        source.href)) ||
                                                                                                        `source-${index}`;
                                                                                                return (
                                                                                                        <SourceChip
                                                                                                                key={sourceKey}
                                                                                                                source={source}
                                                                                                                index={index}
                                                                                                        />
                                                                                                );
                                                                                        })}
                                                                                </div>
                                                                        ) : null}
                                                                        <ConfidenceBadge confidence={message.confidence} />
                                                                </div>
                                                        ) : null}
                                                </div>
                                        );
                                })}
                        </div>
                        <div className="chatbot-input-row">
                                <input
                                        value={query}
                                        onChange={(e) => setQuery(e.target.value)}
                                        placeholder="Ask a question..."
                                        className="chatbot-input"
                                        aria-label="Enter your question"
                                />
                                <button
                                        type="button"
                                        onClick={sendQuery}
                                        className="chatbot-submit"
                                        disabled={!query.trim()}
                                >
                                        Send
                                </button>
                        </div>
                        {hasPendingAssistant ? (
                                <div style={{ color: "#4b5563", fontSize: "0.85rem" }}>
                                        Awaiting response from the assistant...
                                </div>
                        ) : null}
                </div>
        );
}

export default ChatBotPage;
