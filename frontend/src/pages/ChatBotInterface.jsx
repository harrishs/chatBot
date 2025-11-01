import { useParams } from "react-router-dom";
import { useState } from "react";
import api from "../api/axios";
import { buildChatRequest } from "../utils/chatHistory.js";
import { processFeedbackCommand } from "../utils/feedback.js";
import ConfidenceBadge from "../components/ConfidenceBadge.jsx";
import SourceChip from "../components/SourceChip.jsx";

function ChatBotPage({ apiClient = api, chatbotId: overrideId }) {
        const params = useParams();
        const id = overrideId ?? params.id;
        const [query, setQuery] = useState("");
        const [messages, setMessages] = useState([]);
        const [notice, setNotice] = useState("");

        const runChatRequest = async (queryText, options = {}) => {
                const { existingRequestId = null, skipMessageCreation = false, historyMessages } = options;
                const trimmedQuery = queryText.trim();
                if (!trimmedQuery) {
                        return;
                }

                const requestId =
                        existingRequestId ??
                        `${Date.now()}-${Math.random()
                                .toString(36)
                                .slice(2)}`;

                const { url, body } = buildChatRequest({
                        id,
                        messages: historyMessages ?? messages,
                        query: trimmedQuery,
                });

                if (!skipMessageCreation) {
                        setMessages((prev) => [
                                ...prev,
                                { role: "user", content: trimmedQuery, requestId },
                                {
                                        role: "assistant",
                                        content: "",
                                        requestId,
                                        pending: true,
                                        error: false,
                                        sources: [],
                                        confidence: null,
                                        retrievalConfidence: null,
                                        responseMetadata: null,
                                        query: trimmedQuery,
                                },
                        ]);
                        setQuery("");
                }

                try {
                        const res = await apiClient.post(url, body);
                        const data = res?.data ?? {};
                        const answer = data.answer ?? "";
                        setMessages((prev) =>
                                prev.map((message) =>
                                        message.role === "assistant" && message.requestId === requestId
                                                ? {
                                                          ...message,
                                                          content: answer,
                                                          pending: false,
                                                          error: false,
                                                          sources: Array.isArray(data.sources)
                                                                  ? data.sources
                                                                  : [],
                                                          confidence:
                                                                  typeof data.confidence === "number"
                                                                          ? data.confidence
                                                                          : null,
                                                          retrievalConfidence:
                                                                  typeof data.retrieval_confidence === "number"
                                                                          ? data.retrieval_confidence
                                                                          : null,
                                                          responseMetadata: data,
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
                                                          content:
                                                                  "Unable to retrieve a response. Please try again.",
                                                          sources: [],
                                                          confidence: null,
                                                          retrievalConfidence: null,
                                                          responseMetadata: null,
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
                await runChatRequest(trimmedQuery);
        };

        const retryRequest = async (requestId) => {
                let retryQuery = "";
                let updatedMessages = messages;
                setMessages((prev) => {
                        updatedMessages = prev.map((message) => {
                                if (message.role === "assistant" && message.requestId === requestId) {
                                        retryQuery = message.query ?? "";
                                        return {
                                                ...message,
                                                pending: true,
                                                error: false,
                                                content: "",
                                                sources: [],
                                                confidence: null,
                                                retrievalConfidence: null,
                                                responseMetadata: null,
                                        };
                                }
                                return message;
                        });
                        return updatedMessages;
                });

                if (!retryQuery) {
                        return;
                }

                await runChatRequest(retryQuery, {
                        existingRequestId: requestId,
                        skipMessageCreation: true,
                        historyMessages: updatedMessages,
                });
        };

        return (
                <div className="chat-page" style={{ padding: "2rem" }}>
                        <h2>Chat with Bot {id}</h2>
                        {notice ? (
                                <div
                                        role="status"
                                        style={{
                                                backgroundColor: "#e8f5e9",
                                                border: "1px solid #c8e6c9",
                                                color: "#256029",
                                                padding: "0.75rem",
                                                borderRadius: "4px",
                                                marginBottom: "1rem",
                                        }}
                                >
                                        {notice}
                                </div>
                        ) : null}
                        <div className="chat-window">
                                {messages.map((message, index) => (
                                        <div
                                                key={`${message.requestId ?? index}-${message.role}-${index}`}
                                                className={`message-bubble ${message.role}`}
                                        >
                                                <div className="message-role">{message.role}</div>
                                                {message.pending ? (
                                                        <div className="pending-container">
                                                                <span className="chat-spinner" aria-label="Loading" />
                                                                <span className="pending-text">Thinking...</span>
                                                        </div>
                                                ) : message.error ? (
                                                        <div className="error-container">
                                                                <p>{message.content}</p>
                                                                <button
                                                                        type="button"
                                                                        className="retry-button"
                                                                        onClick={() => retryRequest(message.requestId)}
                                                                >
                                                                        Retry
                                                                </button>
                                                        </div>
                                                ) : (
                                                        <p>{message.content}</p>
                                                )}
                                                {!message.pending && !message.error && message.role === "assistant" ? (
                                                        <div className="message-metadata">
                                                                <ConfidenceBadge confidence={message.confidence} />
                                                                {Array.isArray(message.sources) && message.sources.length ? (
                                                                        <div className="chat-sources">
                                                                                {message.sources.map((source, sourceIndex) => (
                                                                                        <SourceChip
                                                                                                // eslint-disable-next-line react/no-array-index-key
                                                                                                key={`${message.requestId}-source-${sourceIndex}`}
                                                                                                source={source}
                                                                                        />
                                                                                ))}
                                                                        </div>
                                                                ) : null}
                                                        </div>
                                                ) : null}
                                        </div>
                                ))}
                        </div>
                        <div className="chat-input-row">
                                <input
                                        value={query}
                                        onChange={(e) => setQuery(e.target.value)}
                                        placeholder="Ask a question..."
                                        className="chat-input"
                                />
                                <button type="button" onClick={sendQuery} className="send-button">
                                        Send
                                </button>
                        </div>
                </div>
        );
}

export default ChatBotPage;
