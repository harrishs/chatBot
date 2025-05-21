import { useEffect, useState } from "react";
import api from "../api/axios";

function ChatBots() {
	const [chatbots, setChatbots] = useState([]);
	const [name, setName] = useState("");
	const [description, setDescription] = useState("");
	const [editingId, setEditingId] = useState(null);

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
		setEditingId(bot.id);
		setName(bot.name);
		setDescription(bot.description);
	};

	const handleDelete = async (id) => {
		if (!window.confirm("Are you sure you want to delete this chatbot?"))
			return;
		try {
			await api.delete(`/chatBots/${id}/`);
			fetchChatbots();
		} catch (err) {
			console.error("Failed to delete chatbot:", err);
		}
	};

	return (
		<div style={{ padding: "2rem" }}>
			<h2>{editingId ? "Edit ChatBot" : "Create ChatBot"}</h2>

			<form onSubmit={handleSubmit} style={{ marginBottom: "2rem" }}>
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

			<ul>
				{chatbots.map((bot) => (
					<li key={bot.id}>
						<strong>{bot.name}</strong>
						<br />
						<small>{bot.description}</small>
						<br />
						<button onClick={() => handleEdit(bot)}>Edit</button>
						<button
							onClick={() => handleDelete(bot.id)}
							style={{ marginLeft: "0.5rem" }}
						>
							Delete
						</button>
					</li>
				))}
			</ul>
		</div>
	);
}

export default ChatBots;
