import { useEffect, useState } from "react";
import api from "../api/axios";

function Credentials() {
	const [name, setName] = useState("");
	const [apiKey, setApiKey] = useState("");
	const [credentials, setCredentials] = useState([]);
	const [email, setEmail] = useState("");

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
			await api.post("/credentials/", {
				name: name,
				api_key: apiKey,
				email: email,
			});

			setName("");
			setApiKey("");
			setEmail("");

			fetchCredentials(); // Refresh the list after adding a new credential
		} catch (err) {
			console.error("Failed to save credentials:", err);
		}
	};

	return (
		<div style={{ padding: "2rem" }}>
			<h2>Create a New API Credential</h2>

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
						type="text"
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
					/>
				</div>
				<button type="submit">Save Credential</button>
			</form>

			<h3>Existing Credentials</h3>
			<ul>
				{credentials.map((cred) => (
					<li key={cred.id}>
						Key Name: <code>{cred.name}</code> <br></br> Email:{" "}
						<code>{cred.email}</code>
					</li>
				))}
			</ul>
		</div>
	);
}

export default Credentials;
