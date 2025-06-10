import { useEffect, useState } from "react";
import api from "../api/axios";

function Credentials() {
	const [name, setName] = useState("");
	const [apiKey, setApiKey] = useState("");
	const [credentials, setCredentials] = useState([]);
	const [email, setEmail] = useState("");
	const [editId, setEditId] = useState(null);

	const fetchCredentials = async () => {
		try {
			const res = await api.get("/credentials/");
			setCredentials(res.data);
		} catch (err) {
			console.error("Error fetching credentials:", err);
		}
	};

	useEffect(() => {
		fetchCredentials();
	}, []);

	const handleSubmit = async (e) => {
		e.preventDefault();
		try {
			if (editId) {
				await api.put(`/credentials/${editId}/`, {
					name: name,
					api_key: apiKey,
					email: email,
				});
			} else {
				await api.post("/credentials/", {
					name: name,
					api_key: apiKey,
					email: email,
				});
			}
			setName("");
			setApiKey("");
			setEmail("");
			setEditId(null);

			fetchCredentials();
		} catch (err) {
			console.error("Failed to save credentials:", err);
		}
	};

	const handleDelete = async (id) => {
		if (!window.confirm("Are you sure you want to delete this credential?"))
			return;
		try {
			await api.delete(`/credentials/${id}/`);
			fetchCredentials();
		} catch (err) {
			console.error("Failed to delete credential:", err);
		}
	};

	const handleEdit = (cred) => {
		setName(cred.name);
		setEmail(cred.email);
		setEditId(cred.id);
		//Api key not available as it is write-only, user must re-enter it
		setApiKey("");
	};

	return (
		<div style={{ padding: "2rem" }}>
			<h2>{editId ? "Edit API Credential" : "Create a New API Credential"}</h2>

			<form onSubmit={handleSubmit} style={{ marginBottom: "2rem" }}>
				<div>
					<label>Name (Label for this key):</label>
					<br />
					<input
						type="text"
						value={name}
						onChange={(e) => setName(e.target.value)}
						required
					/>
				</div>
				<div>
					<label>API Email:</label>
					<br />
					<input
						type="email"
						value={email}
						onChange={(e) => setEmail(e.target.value)}
						required
					/>
				</div>
				<div>
					<label>API Key:</label>
					<br />
					<input
						type="text"
						value={apiKey}
						onChange={(e) => setApiKey(e.target.value)}
						required
						placeholder={editId ? "Enter New/ Existing Key" : ""}
					/>
				</div>
				<button type="submit">{editId ? "Update" : "Save"} Credential</button>
				{editId && (
					<button
						type="button"
						style={{ marginLeft: "1rem" }}
						onClick={() => {
							setEditId(null);
							setName("");
							setApiKey("");
							setEmail("");
						}}
					>
						Cancel
					</button>
				)}
			</form>

			<h3>Existing Credentials</h3>
			<ul>
				{credentials.map((cred) => (
					<li key={cred.id}>
						<strong>{cred.name}</strong> — <code>{cred.email}</code>
						<br />
						<button onClick={() => handleEdit(cred)}>Edit</button>
						<button
							onClick={() => handleDelete(cred.id)}
							style={{ marginLeft: "1rem" }}
						>
							Delete
						</button>
					</li>
				))}
			</ul>
		</div>
	);
}

export default Credentials;
