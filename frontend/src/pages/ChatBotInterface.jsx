import { useParams } from "react-router-dom";
import { useState } from "react";
import api from "../api/axios";
import { buildChatRequest } from "../utils/chatHistory.js";
import { processFeedbackCommand } from "../utils/feedback.js";

function ChatBotPage({ apiClient = api, chatbotId: overrideId }) {
        const params = useParams();
        const id = overrideId ?? params.id;
        const [query, setQuery] = useState("");
        const [messages, setMessages] = useState([]);
        const [notice, setNotice] = useState("");

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

                const { url, body } = buildChatRequest({
                        id,
                        messages,
                        query: trimmedQuery,
                });

                const requestId = `${Date.now()}-${Math.random()
                        .toString(36)
                        .slice(2)}`;

                setMessages((prev) => [
                        ...prev,
                        { role: "user", content: trimmedQuery, requestId },
                        {
                                role: "assistant",
                                content: "",
                                requestId,
                                pending: true,
                        },
                ]);
                setQuery("");

                try {
                        const res = await apiClient.post(url, body);
                        const answer = res?.data?.answer ?? "";
                        setMessages((prev) =>
                                prev.map((message) =>
                                        message.role === "assistant" &&
                                        message.requestId === requestId
                                                ? {
                                                          role: "assistant",
                                                          content: answer,
                                                          requestId,
                                                  }
                                                : message,
                                ),
                        );
                } catch (err) {
                        console.error("Chat error:", err);
                        setMessages((prev) =>
                                prev.map((message) =>
                                        message.role === "assistant" &&
                                        message.requestId === requestId
                                                ? {
                                                          role: "assistant",
                                                          content:
                                                                  "Unable to retrieve a response. Please try again.",
                                                          requestId,
                                                          error: true,
                                                  }
                                                : message,
                                ),
                        );
                }
        };

        return (
                <div style={{ padding: "2rem" }}>
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
                        <div
                                style={{
                                        border: "1px solid #ccc",
                                        padding: "1rem",
                                        height: "300px",
					overflowY: "auto",
				}}
			>
                                {messages.map((m, i) => (
                                        <div key={i}>
                                                <strong>{m.role}:</strong> {m.content}
                                        </div>
                                ))}
			</div>
			<input
				value={query}
				onChange={(e) => setQuery(e.target.value)}
				placeholder="Ask a question..."
			/>
			<button onClick={sendQuery}>Send</button>
		</div>
	);
}

export default ChatBotPage;
