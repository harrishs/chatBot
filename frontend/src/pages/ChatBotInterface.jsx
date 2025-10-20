import { useParams } from "react-router-dom";
import { useState } from "react";
import api from "../api/axios";
import { buildChatRequest } from "../utils/chatHistory.js";

function ChatBotPage({ apiClient = api }) {
        const { id } = useParams();
        const [query, setQuery] = useState("");
        const [messages, setMessages] = useState([]);

        const sendQuery = async () => {
                const trimmedQuery = query.trim();
                if (!trimmedQuery) return;

                const { url, body } = buildChatRequest({
                        id,
                        messages,
                        query: trimmedQuery,
                });

                setMessages((prev) => [
                        ...prev,
                        { role: "user", content: trimmedQuery },
                ]);
                setQuery("");

                try {
                        const res = await apiClient.post(url, body);
                        setMessages((prev) => [
                                ...prev,
                                { role: "assistant", content: res.data.answer },
                        ]);
                } catch (err) {
                        console.error("Chat error:", err);
                }
        };

	return (
		<div style={{ padding: "2rem" }}>
			<h2>Chat with Bot {id}</h2>
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
