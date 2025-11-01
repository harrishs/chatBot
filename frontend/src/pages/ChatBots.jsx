import { useEffect, useState } from "react";
import api from "../api/axios";
import { Link } from "react-router-dom";
import { useAuth } from "../context/AuthContext.jsx";

function ChatBots() {
        const [chatbots, setChatbots] = useState([]);
        const [name, setName] = useState("");
        const [description, setDescription] = useState("");
        const [editingId, setEditingId] = useState(null);
        const { user } = useAuth();
        const canManage = user?.is_staff || user?.role === "admin";

	const fetchChatbots = async () => {
		try {
			const res = await api.get("/chatBots/");
			setChatbots(res.data);
		} catch (err) {
			console.error("Failed to fetch chatbots:", err);
		}
	};

	useEffect(() => {
		fetchChatbots();
	}, []);

        const handleSubmit = async (e) => {
                e.preventDefault();
                if (!canManage) {
                        return;
                }
                try {
                        if (editingId) {
                                await api.put(`/chatBots/${editingId}/`, { name, description });
				setEditingId(null);
			} else {
				await api.post("/chatBots/", { name, description });
			}
			setName("");
			setDescription("");
			fetchChatbots();
		} catch (err) {
			console.error("Failed to save chatbot:", err);
		}
	};

        const handleEdit = (bot) => {
                if (!canManage) {
                        return;
                }
                setEditingId(bot.id);
                setName(bot.name);
                setDescription(bot.description);
        };

        const handleDelete = async (id) => {
                if (!canManage) {
                        return;
                }
                if (!window.confirm("Are you sure you want to delete this chatbot?"))
                        return;
                try {
			await api.delete(`/chatBots/${id}/`);
			setEditingId(null);
			setName("");
			setDescription("");
			fetchChatbots();
		} catch (err) {
			console.error("Failed to delete chatbot:", err);
		}
	};

	return (
                <div style={{ padding: "2rem" }}>
                        <h2>ChatBots</h2>
                        {!canManage && user && (
                                <p style={{ marginTop: "1rem", color: "#555" }}>
                                        You have read-only access. Contact an administrator to manage
                                        chatbots.
                                </p>
                        )}
                        {canManage && (
                                <form onSubmit={handleSubmit} style={{ marginBottom: "2rem" }}>
                                        <h3>{editingId ? "Edit ChatBot" : "Create ChatBot"}</h3>
                                        <div>
                                                <label>Name:</label>
                                                <br />
                                                <input
                                                        value={name}
                                                        onChange={(e) => setName(e.target.value)}
                                                        required
                                                />
                                        </div>
                                        <div>
                                                <label>Description:</label>
                                                <br />
                                                <textarea
                                                        value={description}
                                                        onChange={(e) => setDescription(e.target.value)}
                                                />
                                        </div>
                                        <button type="submit">{editingId ? "Update" : "Create"}</button>
                                        {editingId && (
                                                <button
                                                        type="button"
                                                        onClick={() => {
                                                                setEditingId(null);
                                                                setName("");
                                                                setDescription("");
                                                        }}
                                                >
                                                        Cancel
                                                </button>
                                        )}
                                </form>
                        )}

                        <ul>
                                {chatbots.map((bot) => (
                                        <li key={bot.id}>
                                                <strong>{bot.name}</strong>
                                                <br />
                                                <small>{bot.description}</small>
                                                <br />
                                                <Link to={`/chatbots/${bot.id}`}>💬 Open Chat</Link>
                                                <Link to={`/chatbots/${bot.id}/syncs`}>🔗 Manage Syncs</Link>
                                                {canManage && (
                                                        <>
                                                                <button onClick={() => handleEdit(bot)}>
                                                                        Edit
                                                                </button>
                                                                <button
                                                                        onClick={() => handleDelete(bot.id)}
                                                                        style={{ marginLeft: "0.5rem" }}
                                                                >
                                                                        Delete
                                                                </button>
                                                        </>
                                                )}
                                        </li>
                                ))}
                        </ul>
                </div>
        );
}

export default ChatBots;
